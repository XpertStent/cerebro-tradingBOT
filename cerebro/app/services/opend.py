from moomoo import OpenQuoteContext, RET_OK
import math


class OpenDClient:
    def __init__(self, host: str, port: int, default_market: str = "US"):
        self.host = host
        self.port = port
        self.default_market = default_market

    def _context(self):
        return OpenQuoteContext(
            host=self.host,
            port=self.port
        )

    def normalize_symbol(self, symbol: str) -> str:
        symbol = symbol.strip().upper()

        if "." in symbol:
            return symbol

        return f"{self.default_market}.{symbol}"

    def get_status(self):
        ctx = self._context()

        try:
            ret, data = ctx.get_global_state()

            if ret != RET_OK:
                raise RuntimeError(str(data))

            return {
                "connected": True,
                "quote_server": bool(data.get("qot_logined", False)),
                "trade_server": bool(data.get("trd_logined", False)),
                "version": data.get("server_ver"),
                "program_status": str(
                    data.get("program_status_type", "UNKNOWN")
                )
            }

        finally:
            ctx.close()

    def get_snapshot(self, symbol: str):
        symbol = self.normalize_symbol(symbol)
        ctx = self._context()

        try:
            ret, data = ctx.get_market_snapshot([symbol])

            if ret != RET_OK:
                raise RuntimeError(str(data))

            if data.empty:
                raise RuntimeError(f"No market data returned for {symbol}")

            row = data.iloc[0]

            def clean(value):
                if value is None:
                    return None

                try:
                    if math.isnan(value):
                        return None
                except Exception:
                    pass

                if hasattr(value, "item"):
                    try:
                        return value.item()
                    except Exception:
                        pass

                return value

            return {
                "symbol": clean(row.get("code")),
                "name": clean(row.get("name")),
                "price": clean(row.get("last_price")),
                "open": clean(row.get("open_price")),
                "high": clean(row.get("high_price")),
                "low": clean(row.get("low_price")),
                "previous_close": clean(row.get("prev_close_price")),
                "volume": clean(row.get("volume")),
                "turnover": clean(row.get("turnover")),
                "updated_at": clean(row.get("update_time"))
            }

        finally:
            ctx.close()
