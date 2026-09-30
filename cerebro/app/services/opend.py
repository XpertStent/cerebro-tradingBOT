from moomoo import (
    OpenQuoteContext,
    RET_OK,
    KLType,
    AuType,
    Market,
    SecurityType
)

from app.config import config

import math


class OpenDClient:

    TIMEFRAMES = {
        "1m": KLType.K_1M,
        "5m": KLType.K_5M,
        "15m": KLType.K_15M,
        "30m": KLType.K_30M,
        "60m": KLType.K_60M,
        "1d": KLType.K_DAY,
        "1w": KLType.K_WEEK,
    }

    def __init__(
        self,
        host: str,
        port: int,
        default_market: str = "US"
    ):
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

    @staticmethod
    def _clean(value):

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

    def _snapshot_row(self, row):

        return {
            "symbol": self._clean(row.get("code")),
            "name": self._clean(row.get("name")),

            "price": self._clean(
                row.get("last_price")
            ),
            "open": self._clean(
                row.get("open_price")
            ),
            "high": self._clean(
                row.get("high_price")
            ),
            "low": self._clean(
                row.get("low_price")
            ),
            "previous_close": self._clean(
                row.get("prev_close_price")
            ),

            "volume": self._clean(
                row.get("volume")
            ),
            "turnover": self._clean(
                row.get("turnover")
            ),
            "turnover_rate": self._clean(
                row.get("turnover_rate")
            ),
            "volume_ratio": self._clean(
                row.get("volume_ratio")
            ),

            "highest52weeks_price": self._clean(
                row.get("highest52weeks_price")
            ),
            "lowest52weeks_price": self._clean(
                row.get("lowest52weeks_price")
            ),

            "market_cap": self._clean(
                row.get("total_market_val")
            ),

            "sec_status": self._clean(
                row.get("sec_status")
            ),
            "equity_valid": self._clean(
                row.get("equity_valid")
            ),
            "suspension": self._clean(
                row.get("suspension")
            ),

            "pre_change_rate": self._clean(
                row.get("pre_change_rate")
            ),
            "after_change_rate": self._clean(
                row.get("after_change_rate")
            ),
            "overnight_change_rate": self._clean(
                row.get("overnight_change_rate")
            ),

            "updated_at": self._clean(
                row.get("update_time")
            )
        }

    def get_status(self):

        ctx = self._context()

        try:

            ret, data = ctx.get_global_state()

            if ret != RET_OK:
                raise RuntimeError(str(data))

            return {
                "connected": True,
                "quote_server": bool(
                    data.get("qot_logined", False)
                ),
                "trade_server": bool(
                    data.get("trd_logined", False)
                ),
                "version": data.get("server_ver"),
                "program_status": str(
                    data.get(
                        "program_status_type",
                        "UNKNOWN"
                    )
                )
            }

        finally:
            ctx.close()

    def get_snapshot(self, symbol: str):

        symbol = self.normalize_symbol(symbol)

        ctx = self._context()

        try:

            ret, data = ctx.get_market_snapshot(
                [symbol]
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            if data.empty:
                raise RuntimeError(
                    f"No market data returned for {symbol}"
                )

            return self._snapshot_row(
                data.iloc[0]
            )

        finally:
            ctx.close()

    def get_snapshots(self, symbols: list[str]):

        normalized = [
            self.normalize_symbol(symbol)
            for symbol in symbols
        ]

        ctx = self._context()

        try:

            ret, data = ctx.get_market_snapshot(
                normalized
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            return [
                self._snapshot_row(row)
                for _, row in data.iterrows()
            ]

        finally:
            ctx.close()

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "1d",
        count: int = 100,
        start: str = None,
        end: str = None,
        adjustment: str = "none"
    ):

        symbol = self.normalize_symbol(symbol)
        timeframe = timeframe.lower()

        if timeframe not in self.TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {', '.join(self.TIMEFRAMES)}"
            )

        ctx = self._context()

        try:

            adjustment_map = {
                "none": AuType.NONE,
                "qfq": AuType.QFQ,
            }

            adjustment_key = str(
                adjustment or "none"
            ).lower()

            if adjustment_key not in adjustment_map:
                raise ValueError(
                    f"Unsupported adjustment "
                    f"'{adjustment}'. "
                    f"Supported: none, qfq"
                )

            kwargs = {
                "code": symbol,
                "ktype": self.TIMEFRAMES[timeframe],
                "autype": adjustment_map[
                    adjustment_key
                ],
                "max_count": 1000,
            }

            if start is not None:
                kwargs["start"] = start

            if end is not None:
                kwargs["end"] = end

            ret, data, page_req_key = (
                ctx.request_history_kline(
                    **kwargs
                )
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            # Moomoo may return the oldest rows first.
            # Always return the latest N candles.
            data = data.sort_values(
                by="time_key"
            ).tail(count)

            candles = []

            for _, row in data.iterrows():

                candles.append({
                    "time": self._clean(row.get("time_key")),
                    "open": self._clean(row.get("open")),
                    "high": self._clean(row.get("high")),
                    "low": self._clean(row.get("low")),
                    "close": self._clean(row.get("close")),
                    "volume": self._clean(row.get("volume")),
                    "turnover": self._clean(row.get("turnover"))
                })

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles
            }

        finally:
            ctx.close()


    def get_market_states(self):
        """
        Return all market states exposed by OpenD plus
        human-readable metadata for common markets.
        """

        metadata = {
            "market_us": {
                "id": "US",
                "name": "United States",
                "timezone": "America/New_York",
                "regular_session": "09:30 - 16:00"
            },
            "market_hk": {
                "id": "HK",
                "name": "Hong Kong",
                "timezone": "Asia/Hong_Kong",
                "regular_session": "09:30 - 12:00 / 13:00 - 16:00"
            },
            "market_sh": {
                "id": "SH",
                "name": "Shanghai",
                "timezone": "Asia/Shanghai",
                "regular_session": "09:30 - 11:30 / 13:00 - 15:00"
            },
            "market_sz": {
                "id": "SZ",
                "name": "Shenzhen",
                "timezone": "Asia/Shanghai",
                "regular_session": "09:30 - 11:30 / 13:00 - 15:00"
            },
            "market_jp": {
                "id": "JP",
                "name": "Japan",
                "timezone": "Asia/Tokyo",
                "regular_session": "09:00 - 11:30 / 12:30 - 15:30"
            },
            "market_sg": {
                "id": "SG",
                "name": "Singapore",
                "timezone": "Asia/Singapore",
                "regular_session": "09:00 - 12:00 / 13:00 - 17:00"
            },
            "market_my": {
                "id": "MY",
                "name": "Malaysia",
                "timezone": "Asia/Kuala_Lumpur",
                "regular_session": "09:00 - 12:30 / 14:30 - 17:00"
            }
        }

        ctx = self._context()

        try:
            ret, data = ctx.get_global_state()

            if ret != RET_OK:
                raise RuntimeError(str(data))

            markets = []

            # Don't assume which markets the installed OpenD build exposes.
            # Discover every market_* value dynamically.
            for key, value in data.items():

                if not key.startswith("market_"):
                    continue

                info = metadata.get(
                    key,
                    {
                        "id": key.replace("market_", "").upper(),
                        "name": key.replace("market_", "").replace("_", " ").title(),
                        "timezone": None,
                        "regular_session": None
                    }
                )

                markets.append({
                    **info,
                    "opend_key": key,
                    "state": str(value)
                })

            return sorted(
                markets,
                key=lambda x: x["id"]
            )

        finally:
            ctx.close()


    def search_symbols(
        self,
        query: str,
        markets: list[str] | None = None,
        limit: int = 20
    ):
        query = query.strip().lower()

        if not query:
            return []

        market_map = {
            "US": Market.US,
            "HK": Market.HK,
            "SH": Market.SH,
            "SZ": Market.SZ,
            "SG": Market.SG,
            "MY": Market.MY,
            "JP": Market.JP,
        }

        if not markets:
            markets = list(market_map.keys())

        selected = [
            m.upper()
            for m in markets
            if m.upper() in market_map
        ]

        ctx = self._context()

        try:
            matches = []

            for market_id in selected:

                market_enum = market_map[market_id]

                # Search both equities and ETFs where supported.
                security_types = [
                    SecurityType.STOCK,
                    SecurityType.ETF
                ]

                for security_type in security_types:

                    try:
                        ret, data = ctx.get_stock_basicinfo(
                            market_enum,
                            security_type
                        )

                        if ret != RET_OK:
                            continue

                    except Exception:
                        # Some market/security-type combinations
                        # are not supported by OpenD.
                        continue

                    for _, row in data.iterrows():

                        code = str(row.get("code", ""))
                        name = str(row.get("name", ""))

                        if not code:
                            continue

                        ticker = code.split(".")[-1]

                        q = query
                        ticker_lower = ticker.lower()
                        name_lower = name.lower()

                        score = None

                        if ticker_lower == q:
                            score = 0
                        elif name_lower == q:
                            score = 1
                        elif ticker_lower.startswith(q):
                            score = 2
                        elif name_lower.startswith(q):
                            score = 3
                        elif q in ticker_lower:
                            score = 4
                        elif q in name_lower:
                            score = 5

                        if score is None:
                            continue

                        matches.append({
                            "symbol": code,
                            "ticker": ticker,
                            "name": name,
                            "market": market_id,
                            "security_type": str(security_type),
                            "_score": score
                        })

            # Remove duplicates
            unique = {}

            for item in matches:
                key = item["symbol"]

                if (
                    key not in unique
                    or item["_score"] < unique[key]["_score"]
                ):
                    unique[key] = item

            matches = list(unique.values())

            matches.sort(
                key=lambda x: (
                    x["_score"],
                    x["market"],
                    len(x["ticker"]),
                    x["ticker"]
                )
            )

            results = []

            for item in matches[:limit]:
                item.pop("_score", None)
                results.append(item)

            return results

        finally:
            ctx.close()


opend = OpenDClient(
    host=config["moomoo"]["host"],
    port=config["moomoo"]["port"],
    default_market=config[
        "market_data"
    ]["default_market"]
)
