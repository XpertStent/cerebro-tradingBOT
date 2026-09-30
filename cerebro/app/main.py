from fastapi import FastAPI

from app.config import config
from app.services.opend import opend
from app.services.settings import settings
from app.api.market import router as market_router
from app.api.portfolio import router as portfolio_router
from app.api.orders import router as orders_router
from app.api.markets import router as markets_router
from app.api.activity import router as activity_router
from app.api.strategies import router as strategies_router
from app.api.watchlist import router as watchlist_router
from app.api.ai_memory import router as ai_memory_router
from app.api.scanner import router as scanner_router
from app.api.metrics import router as metrics_router
from app.api.quant_screener import router as quant_screener_router
from app.api.history import router as history_router
from app.api.settings import router as settings_router


NAME = config["cerebro"]["name"]


app = FastAPI(
    title="Cerebro",
    description="Trading bot control and market-data API",
    version="0.3.0"
)


app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(orders_router)
app.include_router(markets_router)
app.include_router(activity_router)
app.include_router(strategies_router)
app.include_router(watchlist_router)
app.include_router(ai_memory_router)
app.include_router(scanner_router)
app.include_router(metrics_router)
app.include_router(quant_screener_router)
app.include_router(history_router)
app.include_router(settings_router)


@app.get("/", tags=["System"])
def root():
    return {
        "service": NAME,
        "version": "0.3.0",
        "status_endpoint": "/system/status",
        "documentation": "/docs"
    }


@app.get("/health", tags=["System"])
def health():
    return {
        "service": NAME,
        "status": "UP"
    }


@app.get("/system/status", tags=["System"])
def system_status():
    trading_enabled = settings.get_bool("trading.enabled")
    trading_mode = str(settings.get("trading.mode")).upper()

    try:
        opend_status = opend.get_status()
        quote_ready = opend_status["quote_server"]

        return {
            "service": NAME,
            "status": "READY" if quote_ready else "WAITING",
            "opend": opend_status,
            "market_data": {
                "status": "READY" if quote_ready else "WAITING"
            },
            "trading": {
                "enabled": trading_enabled,
                "mode": trading_mode,
            },
            "risk": {
                "enabled": settings.get_bool("risk.enabled"),
                "max_order_value": settings.get("risk.max_order_value"),
                "max_daily_loss": settings.get("risk.max_daily_loss"),
            }
        }

    except Exception as e:
        return {
            "service": NAME,
            "status": "DEGRADED",
            "opend": {
                "connected": False,
                "error": str(e)
            },
            "trading": {
                "enabled": trading_enabled,
                "mode": trading_mode,
            }
        }
