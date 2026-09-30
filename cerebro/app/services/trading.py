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
                return value.item()
            except Exception:
                pass

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

            result = {
                "account_id": account_id,
                "environment": "PAPER"
            }

            for field in fields:
                if field in row.index:
                    result[field] = self._clean(row.get(field))

            return result

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


trading = TradingClient(
    host=config["moomoo"]["host"],
    port=config["moomoo"]["port"]
)
