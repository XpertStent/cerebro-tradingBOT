import logging
import threading

from fastapi import FastAPI

from app.config import config
from app.services.opend import opend
from app.services.market_data import market_data
from app.services.settings import settings
from app.services.trading import trading
from app.services.ai_execution import ai_execution
from app.services.ai_thesis_store import ai_theses
from app.services.ai_run_context import ai_run_context
from app.services.live_safety import live_safety
from app.services.live_safety_hardening import install_live_safety_hardening
from app.services.live_trading_hardening import install_hardened_trading
from app.services.live_ai_adapter import install_live_ai_execution
from app.services.live_context_adapter import install_live_context
from app.api.market import router as market_router
from app.api.portfolio import router as portfolio_router
from app.api.orders import router as orders_router
from app.api.trading import router as trading_router
from app.api.markets import router as markets_router
from app.api.activity import router as activity_router
from app.api.watchlist import router as watchlist_router
from app.api.ai_memory import router as ai_memory_router
from app.api.ai_decision import router as ai_decision_router
from app.api.scanner import router as scanner_router
from app.api.metrics import router as metrics_router
from app.api.quant_screener import router as quant_screener_router
from app.api.history import router as history_router
from app.api.settings import router as settings_router


NAME = config["cerebro"]["name"]
install_hardened_trading(trading)
install_live_safety_hardening(live_safety)
install_live_ai_execution(ai_execution)
ai_theses.repair_unapproved_theses()
install_live_context(ai_run_context)


app = FastAPI(
    title="Cerebro",
    description="AI-assisted market research, risk and PAPER/LIVE trading control API",
    version="0.6.0",
)


app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(orders_router)
app.include_router(trading_router)
app.include_router(markets_router)
app.include_router(activity_router)
app.include_router(watchlist_router)
app.include_router(ai_memory_router)
app.include_router(ai_decision_router)
app.include_router(scanner_router)
app.include_router(metrics_router)
app.include_router(quant_screener_router)
app.include_router(history_router)
app.include_router(settings_router)


@app.get("/", tags=["System"])
def root():
    return {
        "service": NAME,
        "version": "0.6.0",
        "status_endpoint": "/system/status",
        "documentation": "/docs",
    }


@app.get("/health", tags=["System"])
def health():
    return {"service": NAME, "status": "UP"}


@app.get("/system/status", tags=["System"])
def system_status():
    trading_enabled = settings.get_bool("trading.enabled")
    trading_mode = str(settings.get("trading.mode") or "paper").upper()

    try:
        opend_status = opend.get_status()
        quote_ready = opend_status["quote_server"]
        data_configuration = market_data.configuration()
        data_status = "READY" if quote_ready else "WAITING"
        if data_configuration["provider"] == "alpaca":
            data_status = "CONFIGURED" if settings.get("alpaca.api_key") and settings.get("alpaca.secret_key") else "CREDENTIALS_REQUIRED"
        trading_state = trading.trading_status(refresh=False)
        trading_ready = bool(trading_state.get("ready"))

        return {
            "service": NAME,
            "status": "READY" if quote_ready else "WAITING",
            "opend": opend_status,
            "market_data": {
                **data_configuration,
                "status": data_status,
                "credentials_note": "Configured keys do not verify provider entitlement; market requests report access failures.",
            },
            "trading": {
                **trading_state,
                "enabled": trading_enabled,
                "mode": trading_mode,
                "status": "READY" if trading_ready else "ATTENTION",
            },
            "risk": {
                "enabled": settings.get_bool("risk.enabled"),
                "max_order_value": settings.get("risk.max_order_value"),
                "max_daily_loss": settings.get("risk.max_daily_loss"),
                "max_position_pct": settings.get("risk.max_position_pct"),
                "max_invested_pct": settings.get("risk.max_invested_pct"),
                "min_cash_reserve_pct": settings.get("risk.min_cash_reserve_pct"),
            },
        }

    except Exception as exc:
        return {
            "service": NAME,
            "status": "DEGRADED",
            "opend": {
                "connected": False,
                "error": str(exc),
            },
            "trading": {
                "enabled": trading_enabled,
                "mode": trading_mode,
                "status": "ATTENTION",
                "error": str(exc),
            },
        }


_history_stop = threading.Event()
_history_thread = None


@app.on_event("startup")
def start_broker_history_refresh():
    global _history_thread
    _history_stop.clear()

    def refresh():
        while not _history_stop.is_set():
            try:
                trading.get_orders()
            except Exception:
                logging.getLogger(__name__).warning("OpenD order history refresh unavailable; retrying in 10 minutes")
            if _history_stop.wait(600):
                break

    _history_thread = threading.Thread(target=refresh, name="broker-history", daemon=True)
    _history_thread.start()

    def warm_symbol_catalog():
        try:
            # Load the catalog using a small query; results are discarded.
            opend.search_symbols("a", markets=["US"], limit=1)
        except Exception:
            logging.getLogger(__name__).warning("OpenD symbol catalog warmup unavailable")

    threading.Thread(target=warm_symbol_catalog, name="symbol-catalog", daemon=True).start()


@app.on_event("shutdown")
def stop_broker_history_refresh():
    _history_stop.set()
    if _history_thread:
        _history_thread.join(timeout=2)
