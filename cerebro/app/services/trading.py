from moomoo import (
    OpenSecTradeContext,
    RET_OK,
    TrdMarket,
    TrdEnv,
    SecurityFirm
)

from app.config import config


class TradingClient:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def _context(self):
        return OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=self.host,
            port=self.port,
            security_firm=SecurityFirm.FUTUINC
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

    def get_accounts(self):
        ctx = self._context()

        try:
            ret, data = ctx.get_acc_list()

            if ret != RET_OK:
                raise RuntimeError(str(data))

            accounts = []

            for _, row in data.iterrows():
                accounts.append({
                    "account_id": self._clean(row.get("acc_id")),
                    "environment": str(row.get("trd_env")),
                    "account_type": str(row.get("acc_type")),
                    "simulation_type": str(row.get("sim_acc_type")),
                    "status": str(row.get("acc_status")),
                    "markets": str(row.get("trdmarket_auth")),
                    "security_firm": str(row.get("security_firm"))
                })

            return accounts

        finally:
            ctx.close()

    def _paper_account_id(self):
        accounts = self.get_accounts()

        for account in accounts:
            if account["environment"].upper() == "SIMULATE":
                return account["account_id"]

        raise RuntimeError("No paper trading account found")

    def get_account_summary(self):
        account_id = self._paper_account_id()
        ctx = self._context()

        try:
            ret, data = ctx.accinfo_query(
                trd_env=TrdEnv.SIMULATE,
                acc_id=account_id
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            if data.empty:
                raise RuntimeError("No account information returned")

            row = data.iloc[0]

            fields = [
                "total_assets",
                "cash",
                "market_val",
                "available_funds",
                "max_power_short",
                "net_cash_power",
                "unrealized_pl",
                "realized_pl"
            ]

            return {
                "account_id": account_id,
                "mode": "PAPER",
                "total_value": self._clean(row.get("total_assets")),
                "cash": self._clean(row.get("cash")),
                "market_value": self._clean(row.get("market_val")),
                "available_cash": self._clean(row.get("available_funds")),
                "unrealized_pnl": self._clean(row.get("unrealized_pl")),
                "realized_pnl": self._clean(row.get("realized_pl"))
            }

        finally:
            ctx.close()

    def get_positions(self):
        account_id = self._paper_account_id()
        ctx = self._context()

        try:
            ret, data = ctx.position_list_query(
                trd_env=TrdEnv.SIMULATE,
                acc_id=account_id,
                refresh_cache=True
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            positions = []

            for _, row in data.iterrows():
                positions.append({
                    "symbol": self._clean(row.get("code")),
                    "name": self._clean(row.get("stock_name")),
                    "quantity": self._clean(row.get("qty")),
                    "available_quantity": self._clean(row.get("can_sell_qty")),
                    "average_cost": self._clean(row.get("cost_price")),
                    "current_price": self._clean(row.get("nominal_price")),
                    "market_value": self._clean(row.get("market_val")),
                    "profit_loss": self._clean(row.get("pl_val")),
                    "profit_loss_percent": self._clean(row.get("pl_ratio"))
                })

            return positions

        finally:
            ctx.close()


    def get_orders(self):
        account_id = self._paper_account_id()
        ctx = self._context()

        try:
            ret, data = ctx.order_list_query(
                trd_env=TrdEnv.SIMULATE,
                acc_id=account_id,
                refresh_cache=True
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            orders = []

            for _, row in data.iterrows():
                orders.append({
                    "order_id": self._clean(row.get("order_id")),
                    "symbol": self._clean(row.get("code")),
                    "name": self._clean(row.get("stock_name")),
                    "side": str(row.get("trd_side")),
                    "order_type": str(row.get("order_type")),
                    "status": str(row.get("order_status")),
                    "quantity": self._clean(row.get("qty")),
                    "price": self._clean(row.get("price")),
                    "filled_quantity": self._clean(row.get("dealt_qty")),
                    "filled_average_price": self._clean(row.get("dealt_avg_price")),
                    "created_at": self._clean(row.get("create_time")),
                    "updated_at": self._clean(row.get("updated_time"))
                })

            return orders

        finally:
            ctx.close()



trading = TradingClient(
    host=config["moomoo"]["host"],
    port=config["moomoo"]["port"]
)
