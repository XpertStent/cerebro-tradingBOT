import sqlite3
import threading
import time
from pathlib import Path

from moomoo import (
    ModifyOrderOp,
    OpenSecTradeContext,
    OrderType,
    RET_OK,
    SecurityFirm,
    TrdEnv,
    TrdMarket,
    TrdSide,
)

from app.services.activity import activity
from app.services.settings import settings


RUNTIME_DB_PATH = Path("/data/cerebro.db")
_RUNTIME_LOCK = threading.RLock()
SUPPORTED_SECURITY_FIRMS = (
    "FUTUINC",
    "FUTUAU",
    "FUTUCA",
    "FUTUSG",
    "FUTUSECURITIES",
)


class TradeUnlockRequired(RuntimeError):
    def __init__(self, message="Live trading is locked. Unlock trading before continuing."):
        super().__init__(f"TRADE_UNLOCK_REQUIRED: {message}")


class TradingClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._cache = {}
        self._cache_ttl = 5.0
        self._unlocked = False
        self._unlock_firm = None
        self._init_runtime_db()

    def _init_runtime_db(self):
        RUNTIME_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._runtime_connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_runtime (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )

    def _runtime_connect(self):
        conn = sqlite3.connect(RUNTIME_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _runtime_get(self, key):
        with _RUNTIME_LOCK:
            with self._runtime_connect() as conn:
                row = conn.execute(
                    "SELECT value FROM trading_runtime WHERE key = ?",
                    (key,),
                ).fetchone()
        return row["value"] if row else None

    def _runtime_set(self, key, value):
        with _RUNTIME_LOCK:
            with self._runtime_connect() as conn:
                conn.execute(
                    """
                    INSERT INTO trading_runtime (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, None if value is None else str(value)),
                )

    @staticmethod
    def _clean(value):
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:
                pass
        if value in ("N/A", "nan", ""):
            return None
        return value

    @staticmethod
    def _enum_text(value):
        text = str(value)
        return text.split(".")[-1].upper()

    @staticmethod
    def _market_list(value):
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).split(".")[-1].upper() for item in value]
        text = str(value).strip("[]")
        return [
            part.strip().strip("'\"").split(".")[-1].upper()
            for part in text.split(",")
            if part.strip()
        ]

    def _cache_get(self, key):
        item = self._cache.get(key)
        if not item:
            return None
        timestamp, value = item
        if time.monotonic() - timestamp > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key, value):
        self._cache[key] = (time.monotonic(), value)
        return value

    def clear_cache(self):
        self._cache.clear()

    def mode(self):
        return str(settings.get("trading.mode") or "paper").strip().lower()

    def environment(self):
        return TrdEnv.REAL if self.mode() == "live" else TrdEnv.SIMULATE

    def mode_changed(self):
        self.clear_cache()
        self._unlocked = False
        self._unlock_firm = None

    def _firm_enum(self, name):
        firm = getattr(SecurityFirm, str(name), None)
        if firm is None:
            raise RuntimeError(f"Moomoo API does not expose security firm {name}")
        return firm

    def _context(self, security_firm="FUTUINC"):
        return OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=self.host,
            port=self.port,
            security_firm=self._firm_enum(security_firm),
        )

    def _accounts_for_firm(self, firm_name):
        ctx = self._context(firm_name)
        try:
            ret, data = ctx.get_acc_list()
            if ret != RET_OK:
                raise RuntimeError(str(data))
            accounts = []
            for _, row in data.iterrows():
                environment = self._enum_text(row.get("trd_env"))
                account = {
                    "account_id": self._clean(row.get("acc_id")),
                    "environment": environment,
                    "account_type": self._enum_text(row.get("acc_type")),
                    "simulation_type": self._enum_text(row.get("sim_acc_type")),
                    "status": self._enum_text(row.get("acc_status")),
                    "markets": self._market_list(row.get("trdmarket_auth")),
                    "security_firm": (
                        self._enum_text(row.get("security_firm"))
                        if environment == "REAL"
                        else firm_name
                    ),
                    "universal_account": self._clean(row.get("uni_card_num")),
                    "trading_account": self._clean(row.get("card_num")),
                }
                accounts.append(account)
            return accounts
        finally:
            ctx.close()

    def get_accounts(self, refresh=False):
        cache_key = "all_accounts"
        if not refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        discovered = {}
        errors = []
        for firm_name in SUPPORTED_SECURITY_FIRMS:
            if getattr(SecurityFirm, firm_name, None) is None:
                continue
            try:
                for account in self._accounts_for_firm(firm_name):
                    key = (
                        str(account.get("account_id")),
                        str(account.get("environment")),
                    )
                    existing = discovered.get(key)
                    if existing is None or account["environment"] == "REAL":
                        discovered[key] = account
            except Exception as exc:
                errors.append(f"{firm_name}: {exc}")

        accounts = list(discovered.values())
        if not accounts and errors:
            raise RuntimeError("Unable to discover Moomoo accounts: " + " | ".join(errors))

        selected_live = self._runtime_get("live_account_id")
        for account in accounts:
            account["selected"] = (
                account["environment"] == "REAL"
                and str(account.get("account_id")) == str(selected_live)
            )
        accounts.sort(
            key=lambda item: (
                0 if item["environment"] == "REAL" else 1,
                0 if item.get("status") == "ACTIVE" else 1,
                str(item.get("account_id")),
            )
        )
        return self._cache_set(cache_key, accounts)

    def _is_us_authorized(self, account):
        markets = {str(item).upper() for item in (account.get("markets") or [])}
        return "US" in markets

    def _live_candidates(self, refresh=False):
        return [
            account
            for account in self.get_accounts(refresh=refresh)
            if account.get("environment") == "REAL"
            and account.get("status") == "ACTIVE"
            and self._is_us_authorized(account)
        ]

    def select_live_account(self, account_id):
        account_id = str(account_id)
        candidates = self._live_candidates(refresh=True)
        account = next(
            (
                item
                for item in candidates
                if str(item.get("account_id")) == account_id
            ),
            None,
        )
        if account is None:
            raise RuntimeError(
                "Selected account is not an ACTIVE REAL account with US trading permission"
            )
        self._runtime_set("live_account_id", account_id)
        self._runtime_set("live_security_firm", account.get("security_firm"))
        self._unlocked = False
        self._unlock_firm = None
        self.clear_cache()
        activity.write(
            category="BROKER",
            action="LIVE_ACCOUNT_SELECTED",
            message=f"Selected REAL trading account ending {account_id[-4:]}",
            level="WARN",
            details={
                "environment": "LIVE",
                "account_id": account_id,
                "security_firm": account.get("security_firm"),
                "markets": account.get("markets"),
            },
        )
        return account

    def _paper_account(self):
        accounts = self.get_accounts()
        candidates = [
            account
            for account in accounts
            if account.get("environment") == "SIMULATE"
            and (
                not account.get("markets")
                or self._is_us_authorized(account)
                or account.get("simulation_type") == "STOCK"
            )
        ]
        if not candidates:
            raise RuntimeError("No US paper trading account found")
        return candidates[0]

    def _live_account(self, refresh=False):
        candidates = self._live_candidates(refresh=refresh)
        selected_id = self._runtime_get("live_account_id")
        if selected_id:
            selected = next(
                (
                    item
                    for item in candidates
                    if str(item.get("account_id")) == str(selected_id)
                ),
                None,
            )
            if selected is not None:
                return selected

        if len(candidates) == 1:
            return self.select_live_account(candidates[0]["account_id"])
        if not candidates:
            raise RuntimeError(
                "No ACTIVE REAL Moomoo account with US trading permission was found"
            )
        raise RuntimeError(
            "Multiple LIVE accounts are available. Select the intended account in the Live Trading control."
        )

    def current_account(self, refresh=False):
        return self._live_account(refresh=refresh) if self.mode() == "live" else self._paper_account()

    def current_account_id(self, refresh=False):
        return self.current_account(refresh=refresh)["account_id"]

    def current_security_firm(self, refresh=False):
        account = self.current_account(refresh=refresh)
        return account.get("security_firm") or "FUTUINC"

    def trading_status(self, refresh=False):
        mode = self.mode()
        base = {
            "mode": mode.upper(),
            "enabled": settings.get_bool("trading.enabled"),
            "unlock_required": mode == "live",
            "unlocked": bool(self._unlocked) if mode == "live" else True,
            "account": None,
            "available_live_accounts": [],
            "ready": False,
        }
        try:
            if mode == "live":
                candidates = self._live_candidates(refresh=refresh)
                base["available_live_accounts"] = candidates
                try:
                    account = self._live_account(refresh=False)
                except RuntimeError as exc:
                    base["error"] = str(exc)
                    return base
            else:
                account = self._paper_account()
            base["account"] = account
            base["ready"] = bool(
                settings.get_bool("trading.enabled")
                and account
                and account.get("status") in {"ACTIVE", "N/A", ""}
            )
            return base
        except Exception as exc:
            base["error"] = str(exc)
            return base

    def get_account_summary(self, refresh=False):
        mode = self.mode()
        cache_key = f"account_summary:{mode}"
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
                trd_env=self.environment(),
                acc_id=account_id,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            if data.empty:
                raise RuntimeError("No account information returned")
            row = data.iloc[0]
            result = {
                "account_id": account_id,
                "account_id_masked": f"••••{str(account_id)[-4:]}",
                "mode": mode.upper(),
                "security_firm": firm,
                "account_type": account.get("account_type"),
                "total_value": self._clean(row.get("total_assets")),
                "cash": self._clean(row.get("cash")),
                "market_value": self._clean(row.get("market_val")),
                "available_cash": self._clean(row.get("available_funds")),
                "buying_power": self._clean(row.get("power")),
                "unrealized_pnl": self._clean(row.get("unrealized_pl")),
                "realized_pnl": self._clean(row.get("realized_pl")),
            }
            return self._cache_set(cache_key, result)
        finally:
            ctx.close()

    def get_positions(self, refresh=False):
        mode = self.mode()
        cache_key = f"positions:{mode}"
        if not refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        account = self.current_account(refresh=refresh)
        account_id = account["account_id"]
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            ret, data = ctx.position_list_query(
                trd_env=self.environment(),
                acc_id=account_id,
                refresh_cache=True,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            positions = []
            for _, row in data.iterrows():
                positions.append(
                    {
                        "symbol": self._clean(row.get("code")),
                        "name": self._clean(row.get("stock_name")),
                        "quantity": self._clean(row.get("qty")),
                        "available_quantity": self._clean(row.get("can_sell_qty")),
                        "average_cost": self._clean(row.get("cost_price")),
                        "current_price": self._clean(row.get("nominal_price")),
                        "market_value": self._clean(row.get("market_val")),
                        "profit_loss": self._clean(row.get("pl_val")),
                        "profit_loss_percent": self._clean(row.get("pl_ratio")),
                        "mode": mode.upper(),
                    }
                )
            return self._cache_set(cache_key, positions)
        finally:
            ctx.close()

    def get_orders(self):
        account = self.current_account()
        account_id = account["account_id"]
        firm = account.get("security_firm") or "FUTUINC"
        mode = self.mode()
        ctx = self._context(firm)
        try:
            ret, data = ctx.order_list_query(
                trd_env=self.environment(),
                acc_id=account_id,
                refresh_cache=True,
            )
            if ret != RET_OK:
                raise RuntimeError(str(data))
            orders = []
            for _, row in data.iterrows():
                orders.append(
                    {
                        "order_id": self._clean(row.get("order_id")),
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
                        "mode": mode.upper(),
                        "account_id": account_id,
                    }
                )
            return orders
        finally:
            ctx.close()

    def unlock_trade(self, *, password=None, password_md5=None):
        if self.mode() != "live":
            return {"unlocked": True, "mode": "PAPER", "message": "Paper trading does not require unlock"}
        if not password and not password_md5:
            raise ValueError("Trading password is required")

        account = self._live_account(refresh=True)
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            ret, data = ctx.unlock_trade(
                password=password or None,
                password_md5=password_md5 or None,
                is_unlock=True,
            )
            if ret != RET_OK:
                self._unlocked = False
                raise RuntimeError(str(data))
        finally:
            ctx.close()

        self._unlocked = True
        self._unlock_firm = firm
        activity.write(
            category="SECURITY",
            action="LIVE_TRADING_UNLOCKED",
            message="Moomoo live trading was unlocked through Cerebro",
            level="WARN",
            details={
                "environment": "LIVE",
                "account_id": account.get("account_id"),
                "security_firm": firm,
            },
        )
        return {
            "unlocked": True,
            "mode": "LIVE",
            "account_id": account.get("account_id"),
            "security_firm": firm,
        }

    def lock_trade(self):
        if self.mode() != "live":
            return {"unlocked": True, "mode": "PAPER"}
        account = self._live_account()
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            ret, data = ctx.unlock_trade(is_unlock=False)
            if ret != RET_OK:
                raise RuntimeError(str(data))
        finally:
            ctx.close()
        self._unlocked = False
        self._unlock_firm = None
        activity.write(
            category="SECURITY",
            action="LIVE_TRADING_LOCKED",
            message="Moomoo live trading was locked through Cerebro",
            level="WARN",
            details={
                "environment": "LIVE",
                "account_id": account.get("account_id"),
                "security_firm": firm,
            },
        )
        return {"unlocked": False, "mode": "LIVE"}

    def ensure_unlocked(self):
        if self.mode() == "live" and not self._unlocked:
            raise TradeUnlockRequired()

    def _handle_broker_error(self, data):
        text = str(data)
        lower = text.lower()
        if self.mode() == "live" and ("unlock" in lower or "locked" in lower):
            self._unlocked = False
            raise TradeUnlockRequired(text)
        raise RuntimeError(text)

    def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        remark: str | None = None,
    ):
        side = str(side).upper()
        order_type = str(order_type).upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if order_type not in {"MARKET", "LIMIT"}:
            raise ValueError("order_type must be MARKET or LIMIT")
        if order_type == "LIMIT" and price is None:
            raise ValueError("LIMIT order requires price")

        self.ensure_unlocked()
        account = self.current_account(refresh=True)
        account_id = account["account_id"]
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            kwargs = {
                "qty": quantity,
                "code": symbol,
                "trd_side": TrdSide.BUY if side == "BUY" else TrdSide.SELL,
                "order_type": OrderType.MARKET if order_type == "MARKET" else OrderType.NORMAL,
                "trd_env": self.environment(),
                "acc_id": account_id,
                "price": 0 if order_type == "MARKET" else price,
            }
            if remark:
                kwargs["remark"] = str(remark)[:64]
            ret, data = ctx.place_order(**kwargs)
            if ret != RET_OK:
                self._handle_broker_error(data)
            if data.empty:
                raise RuntimeError("OpenD returned no order data")
            row = data.iloc[0]
            result = {
                "order_id": self._clean(row.get("order_id")),
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
                "remark": self._clean(row.get("remark")) or remark,
                "mode": self.mode().upper(),
                "account_id": account_id,
                "security_firm": firm,
            }
            self.clear_cache()
            return result
        finally:
            ctx.close()

    def place_paper_order(self, **kwargs):
        return self.place_order(**kwargs)

    def cancel_order(self, order_id):
        self.ensure_unlocked()
        existing = next(
            (
                item
                for item in self.get_orders()
                if str(item.get("order_id")) == str(order_id)
            ),
            None,
        )
        if existing is None:
            raise RuntimeError("Order not found")

        account = self.current_account()
        firm = account.get("security_firm") or "FUTUINC"
        ctx = self._context(firm)
        try:
            ret, data = ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=str(order_id),
                qty=0,
                price=0,
                trd_env=self.environment(),
                acc_id=account["account_id"],
            )
            if ret != RET_OK:
                self._handle_broker_error(data)
        finally:
            ctx.close()
        self.clear_cache()
        return existing


trading = TradingClient("127.0.0.1", 11111)
