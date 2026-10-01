import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MethodType
from zoneinfo import ZoneInfo

from moomoo import Currency, ModifyOrderOp, OrderType, RET_OK, TrdEnv, TrdMarket, TrdSide

from app.services.broker_history import broker_history
from app.services.broker_identity import broker_id
from app.services.account_fields import securities_funds, position_pnl
from app.services.activity import activity
from app.services.execution_context import build_execution_context


DB_PATH = Path("/data/cerebro.db")
EXECUTION_LOCK = threading.RLock()
NY = ZoneInfo("America/New_York")


class LiveTradingHardening:
    """Correctness layer for the LIVE branch.

    This module deliberately keeps the original TradingClient small while
    hardening real-money behaviour: USD-normalised account funds, persistent
    execution intents, atomic account binding, broker max-quantity checks,
    90-day order history, and a conservative daily account drawdown guard.
    """

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_intents (
                    intent_id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    broker_remark TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_account_baseline (
                    context_id TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    baseline_assets REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (context_id, trade_date)
                )
                """
            )

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _f(value, default=None):
        if value in (None, "", "N/A", "nan"):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _trade_date():
        return datetime.now(NY).date().isoformat()

    def daily_equity_pnl(self, *, context_id: str, current_assets: float):
        """Return change from the first observed LIVE net-assets value of the US day.

        This intentionally avoids Moomoo's `realized_pl`, which is futures-only.
        It is a conservative account-value drawdown guard: market losses can stop
        new risk even before positions are sold. External cash movements may move
        the value and are therefore exposed in the returned metadata.
        """
        trade_date = self._trade_date()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT baseline_assets, created_at FROM daily_account_baseline WHERE context_id=? AND trade_date=?",
                (context_id, trade_date),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO daily_account_baseline(context_id, trade_date, baseline_assets, created_at) VALUES(?,?,?,?)",
                    (context_id, trade_date, float(current_assets), self._now()),
                )
                baseline = float(current_assets)
                created_at = self._now()
            else:
                baseline = float(row["baseline_assets"])
                created_at = row["created_at"]
        return {
            "trade_date": trade_date,
            "baseline_assets": baseline,
            "current_assets": float(current_assets),
            "daily_pnl": float(current_assets) - baseline,
            "baseline_created_at": created_at,
            "method": "ACCOUNT_EQUITY_CHANGE",
        }

    def get_intent(self, intent_id: str):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_intents WHERE intent_id=?",
                (str(intent_id),),
            ).fetchone()
        return dict(row) if row else None

    def put_intent(self, *, intent_id, context_id, source, symbol, side, quantity, status="PENDING_SUBMISSION", remark=None):
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO execution_intents(intent_id, context_id, source, symbol, side, quantity, status, broker_remark, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(intent_id) DO NOTHING
                """,
                (str(intent_id), str(context_id), str(source), str(symbol), str(side), float(quantity), str(status), remark, now, now),
            )
        return self.get_intent(intent_id)

    def update_intent(self, intent_id, *, status, broker_order_id=None, remark=None, error=None):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE execution_intents
                SET status=?, broker_order_id=COALESCE(?, broker_order_id), broker_remark=COALESCE(?, broker_remark), error=?, updated_at=?
                WHERE intent_id=?
                """,
                (status, broker_order_id, remark, error, self._now(), str(intent_id)),
            )
        return self.get_intent(intent_id)


hardening = LiveTradingHardening()


def install_hardened_trading(trading):
    if getattr(trading, "_live_hardening_installed", False):
        return trading

    original_summary = trading.get_account_summary
    original_select = trading.select_live_account
    original_mode_changed = trading.mode_changed

    def current_execution_context(self, refresh=False):
        mode = self.mode().upper()
        account = self.current_account(refresh=refresh)
        return build_execution_context(mode=mode, account=account)

    def mode_changed(self):
        with EXECUTION_LOCK:
            return original_mode_changed()

    def select_live_account(self, account_id):
        with EXECUTION_LOCK:
            return original_select(account_id)

    def get_account_summary(self, refresh=False):
        if self.mode() != "live":
            return original_summary(refresh=refresh)

        cache_key = "account_summary:live:usd"
        if not refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        account = self.current_account(refresh=refresh)
        account_id = account["account_id"]
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            ret, data = ctx.accinfo_query(
                trd_env=TrdEnv.REAL,
                acc_id=int(account_id),
                refresh_cache=bool(refresh),
                currency=Currency.USD,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            if data.empty:
                raise RuntimeError("No LIVE account information returned")
            row = data.iloc[0]

            funds = securities_funds(row)
            total_value = funds["total_value"]
            if total_value is None:
                raise RuntimeError("LIVE USD account value is unavailable")
            positions = self.get_positions(refresh=refresh)
            us_positions = [p for p in positions if str(p.get("symbol", "")).startswith("US.")]
            pnl = position_pnl(us_positions)

            execution_context = build_execution_context(mode="LIVE", account=account)
            daily = hardening.daily_equity_pnl(
                context_id=execution_context["context_id"],
                current_assets=total_value,
            )
            result = {
                "account_id": account_id,
                "account_id_masked": f"••••{str(account_id)[-4:]}",
                "universal_account_masked": account.get("universal_account_masked"),
                "trading_account_masked": account.get("trading_account_masked"),
                "mode": "LIVE",
                "currency": "USD",
                "security_firm": firm,
                "account_type": account.get("account_type"),
                **funds,
                **pnl,
                "daily_pnl": daily["daily_pnl"],
                "daily_pnl_method": daily["method"],
                "daily_pnl_baseline": daily["baseline_assets"],
                "execution_context_id": execution_context["context_id"],
            }
            return self._cache_set(cache_key, result)
        finally:
            ctx.close()

    def _map_order(self, row, *, mode, account_id):
        return {
            "order_id": broker_id(row.get("order_id")),
            "symbol": self._clean(row.get("code")),
            "name": self._clean(row.get("stock_name")),
            "side": self._enum_text(row.get("trd_side")),
            "order_type": self._enum_text(row.get("order_type")),
            "status": self._enum_text(row.get("order_status")),
            "quantity": self._clean(row.get("qty")),
            "price": self._clean(row.get("price")),
            "filled_quantity": self._clean(row.get("dealt_qty")),
            "filled_average_price": self._clean(row.get("dealt_avg_price")),
            "created_at": self._clean(row.get("create_time")),
            "updated_at": self._clean(row.get("updated_time")),
            "remark": self._clean(row.get("remark")),
            "mode": mode,
            "account_id": account_id,
        }

    def _get_orders(self, history_days=90, refresh_history=False):
        account = self.current_account()
        account_id = account["account_id"]
        firm = account.get("security_firm") or "FUTUINC"
        mode = self.mode().upper()
        env = TrdEnv.REAL if mode == "LIVE" else TrdEnv.SIMULATE
        ctx = self._context(firm)
        context = build_execution_context(mode=mode, account=account)["context_id"]
        merged = {}
        try:
            ret, data = ctx.order_list_query(
                trd_env=env,
                acc_id=int(account_id),
                refresh_cache=True,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            for _, row in data.iterrows():
                item = self._map_order(row, mode=mode, account_id=account_id)
                item.update(source="OpenD", broker_query="order_list_query", security_firm=firm)
                merged[str(item.get("order_id"))] = item

            def load_history():
                now = datetime.now(NY)
                start = (now - timedelta(days=max(1, min(int(history_days), 90)))).strftime("%Y-%m-%d 00:00:00")
                ret, history = ctx.history_order_list_query(
                    start=start, end=now.strftime("%Y-%m-%d %H:%M:%S"),
                    trd_env=env, acc_id=int(account_id), order_market=TrdMarket.US,
                )
                if ret != RET_OK:
                    raise RuntimeError("OpenD history unavailable")
                result = []
                for _, row in history.iterrows():
                    item = self._map_order(row, mode=mode, account_id=account_id)
                    item.update(source="OpenD", broker_query="history_order_list_query", security_firm=firm)
                    result.append(item)
                return result

            historical, refreshed, stale = broker_history.history(context, load_history, force=refresh_history)
            for item in historical:
                # A persisted record never becomes proof of a current pending order.
                if item.get("status") not in {"FILLED_ALL", "CANCELLED_ALL", "CANCELED_ALL", "FAILED", "DISABLED", "DELETED"}:
                    continue
                merged.setdefault(str(item.get("order_id")), item)
            result = sorted(merged.values(), key=lambda item: str(item.get("created_at") or ""))
            broker_history.save(context, result, refreshed)
            self._order_history_status = {
                "source": "OpenD", "context_id": context, "account_id": str(account_id),
                "mode": mode, "security_firm": firm, "timezone": "America/New_York",
                "history_refreshed_at": broker_history.timestamp(refreshed),
                "history_stale": stale, "refresh_interval_seconds": broker_history.interval,
                "current_orders_verified_at": datetime.now(timezone.utc).isoformat(),
            }
            return result
        finally:
            ctx.close()

    def get_orders(self, history_days=90, refresh_history=False):
        with EXECUTION_LOCK:
            return _get_orders(self, history_days, refresh_history)

    def find_order_by_remark(self, remark):
        target = str(remark or "")
        if not target:
            return None
        return next((item for item in self.get_orders() if str(item.get("remark") or "") == target), None)

    def max_tradable_quantity(self, *, symbol, side, order_type, price, account=None, environment=None):
        account = account or self.current_account(refresh=True)
        firm = account.get("security_firm") or "FUTUINC"
        env = environment or self.environment()
        broker_order_type = OrderType.MARKET if str(order_type).upper() == "MARKET" else OrderType.NORMAL
        px = float(price or 0)
        if px <= 0:
            raise RuntimeError("A positive reference price is required for broker max-quantity validation")
        ctx = self._context(firm)
        try:
            ret, data = ctx.acctradinginfo_query(
                order_type=broker_order_type,
                code=str(symbol).upper(),
                price=px,
                trd_env=env,
                acc_id=int(account["account_id"]),
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            if data.empty:
                raise RuntimeError("Broker returned no maximum tradable quantity")
            row = data.iloc[0]
            if str(side).upper() == "BUY":
                # Cash-only by policy: intentionally do not use max_cash_and_margin_buy.
                maximum = hardening._f(row.get("max_cash_buy"), 0.0)
                field = "max_cash_buy"
            else:
                maximum = hardening._f(row.get("max_position_sell"), 0.0)
                field = "max_position_sell"
            return {"maximum": maximum, "field": field}
        finally:
            ctx.close()

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        remark: str | None = None,
        expected_context_id: str | None = None,
        intent_id: str | None = None,
        source: str = "MANUAL",
        reference_price: float | None = None,
    ):
        side = str(side).upper()
        order_type = str(order_type).upper()
        symbol = str(symbol).upper()
        if not symbol.startswith("US."):
            raise RuntimeError("Cerebro execution is restricted to US securities")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("order_type must be MARKET or LIMIT")
        if order_type == "LIMIT" and price is None:
            raise ValueError("LIMIT order requires price")

        intent_id = str(intent_id or uuid.uuid4().hex)
        with EXECUTION_LOCK:
            mode = self.mode().upper()
            account = self.current_account(refresh=True)
            context = build_execution_context(mode=mode, account=account)
            if expected_context_id and context["context_id"] != str(expected_context_id):
                raise RuntimeError("EXECUTION_CONTEXT_MISMATCH: active account/environment changed before broker submission")
            if mode == "LIVE" and not self._unlocked:
                from app.services.trading import TradeUnlockRequired
                raise TradeUnlockRequired()

            broker_remark = (remark or f"CEREBRO:{source}:{intent_id}")[:64]
            existing = hardening.get_intent(intent_id)
            if existing:
                if existing["context_id"] != context["context_id"]:
                    raise RuntimeError("EXECUTION_CONTEXT_MISMATCH: intent belongs to another account/environment")
                broker_existing = self.find_order_by_remark(existing.get("broker_remark") or broker_remark)
                if broker_existing:
                    hardening.update_intent(intent_id, status="SUBMITTED", broker_order_id=broker_existing.get("order_id"), remark=broker_remark)
                    return broker_existing
                if existing.get("status") == "SUBMITTED":
                    raise RuntimeError("Execution intent was already submitted; broker reconciliation has not returned the order yet")
            else:
                hardening.put_intent(
                    intent_id=intent_id,
                    context_id=context["context_id"],
                    source=source,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    remark=broker_remark,
                )

            env = TrdEnv.REAL if mode == "LIVE" else TrdEnv.SIMULATE
            firm = account.get("security_firm") or "FUTUINC"
            broker_price = float(price) if order_type == "LIMIT" else float(reference_price or 0)
            if mode == "LIVE":
                maximum = self.max_tradable_quantity(
                    symbol=symbol,
                    side=side,
                    order_type=order_type,
                    price=broker_price,
                    account=account,
                    environment=env,
                )
                if float(quantity) > float(maximum["maximum"]) + 1e-9:
                    hardening.update_intent(intent_id, status="BLOCKED", remark=broker_remark, error="BROKER_MAX_QUANTITY")
                    raise RuntimeError(
                        f"Broker maximum {side.lower()} quantity is {maximum['maximum']:g} shares ({maximum['field']}); requested {float(quantity):g}"
                    )

            # Final context check immediately before the broker call. The call
            # below uses the captured account/env, so even a concurrent UI mode
            # change cannot redirect this order to a different account.
            final_mode = self.mode().upper()
            final_account = self.current_account(refresh=True)
            final_context = build_execution_context(mode=final_mode, account=final_account)
            if final_context["context_id"] != context["context_id"]:
                hardening.update_intent(intent_id, status="BLOCKED", remark=broker_remark, error="EXECUTION_CONTEXT_CHANGED")
                raise RuntimeError("EXECUTION_CONTEXT_MISMATCH: account/environment changed immediately before broker submission")

            ctx = self._context(firm)
            try:
                kwargs = {
                    "qty": quantity,
                    "code": symbol,
                    "trd_side": TrdSide.BUY if side == "BUY" else TrdSide.SELL,
                    "order_type": OrderType.MARKET if order_type == "MARKET" else OrderType.NORMAL,
                    "trd_env": env,
                    "acc_id": int(account["account_id"]),
                    "price": 0 if order_type == "MARKET" else price,
                    "remark": broker_remark,
                }
                try:
                    ret, data = ctx.place_order(**kwargs)
                except Exception as exc:
                    hardening.update_intent(intent_id, status="UNKNOWN", remark=broker_remark, error=str(exc))
                    raise
                if ret != RET_OK:
                    hardening.update_intent(intent_id, status="FAILED", remark=broker_remark, error=str(data))
                    self._handle_broker_error(data)
                if data.empty:
                    hardening.update_intent(intent_id, status="UNKNOWN", remark=broker_remark, error="EMPTY_BROKER_RESPONSE")
                    raise RuntimeError("OpenD returned no order data; intent left UNKNOWN for reconciliation")
                row = data.iloc[0]
                result = self._map_order(row, mode=mode, account_id=account["account_id"])
                result["security_firm"] = firm
                result["intent_id"] = intent_id
                hardening.update_intent(
                    intent_id,
                    status="SUBMITTED",
                    broker_order_id=result.get("order_id"),
                    remark=broker_remark,
                )
                self.clear_cache()
                return result
            finally:
                ctx.close()

    def cancel_order(self, order_id):
        with EXECUTION_LOCK:
            self.ensure_unlocked()
            existing = next((item for item in self.get_orders() if str(item.get("order_id")) == str(order_id)), None)
            if existing is None:
                raise RuntimeError("Order not found")
            account = self.current_account(refresh=True)
            firm = account.get("security_firm") or "FUTUINC"
            mode = self.mode().upper()
            env = TrdEnv.REAL if mode == "LIVE" else TrdEnv.SIMULATE
            ctx = self._context(firm)
            try:
                ret, data = ctx.modify_order(
                    modify_order_op=ModifyOrderOp.CANCEL,
                    order_id=str(order_id),
                    qty=0,
                    price=0,
                    trd_env=env,
                    acc_id=int(account["account_id"]),
                )
                if ret != RET_OK:
                    self._handle_broker_error(data)
            finally:
                ctx.close()
            self.clear_cache()
            return existing

    trading.current_execution_context = MethodType(current_execution_context, trading)
    trading.mode_changed = MethodType(mode_changed, trading)
    trading.select_live_account = MethodType(select_live_account, trading)
    trading.get_account_summary = MethodType(get_account_summary, trading)
    trading._map_order = MethodType(_map_order, trading)
    trading.get_orders = MethodType(get_orders, trading)
    trading.find_order_by_remark = MethodType(find_order_by_remark, trading)
    trading.max_tradable_quantity = MethodType(max_tradable_quantity, trading)
    trading.place_order = MethodType(place_order, trading)
    trading.cancel_order = MethodType(cancel_order, trading)
    trading._live_hardening_installed = True
    return trading
