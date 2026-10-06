from moomoo import (
    OpenQuoteContext,
    RET_OK,
    KLType,
    AuType,
    Market,
    SecurityType
)

from app.config import config
from app.services.symbol_catalog import SymbolCatalogCache, SymbolCatalogTimeout
from app.services.history_quota import HistoricalCandleQuotaError, check_history_reserve, is_history_quota_error

import math
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


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
        self._symbol_catalog = SymbolCatalogCache()

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

    def check_history_capacity(self, symbol, reserve):
        if reserve <= 0:
            return
        ctx = self._context()
        try:
            ret, quota = ctx.get_history_kl_quota(get_detail=True)
            if ret != RET_OK:
                raise RuntimeError("Historical analysis paused: OpenD candle quota could not be checked.")
            check_history_reserve(self.normalize_symbol(symbol), quota, reserve)
        finally:
            ctx.close()

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "1d",
        count: int = 100,
        start: str = None,
        end: str = None,
        adjustment: str = "none",
        before: str = None
    ):

        symbol = self.normalize_symbol(symbol)
        timeframe = timeframe.lower()

        if timeframe not in self.TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported: {', '.join(self.TIMEFRAMES)}"
            )

        if before:
            before = datetime.fromisoformat(before).strftime("%Y-%m-%d %H:%M:%S")

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

            market_timezone = {"US":"America/New_York", "HK":"Asia/Hong_Kong", "SH":"Asia/Shanghai", "SZ":"Asia/Shanghai", "SG":"Asia/Singapore", "MY":"Asia/Kuala_Lumpur", "JP":"Asia/Tokyo"}.get(symbol.split(".")[0], "Asia/Hong_Kong")
            now = datetime.now(ZoneInfo(market_timezone))
            minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
            if timeframe in minutes:
                lookback_days = max(7, math.ceil(count * minutes[timeframe] / 390 * 2) + 7)
            else:
                lookback_days = count * (14 if timeframe == "1w" else 2) + 14
            kwargs["end"] = end or (before[:10] if before else now.strftime("%Y-%m-%d"))
            end_date = datetime.strptime(kwargs["end"][:10], "%Y-%m-%d")
            kwargs["start"] = start or (end_date - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

            # History pages are oldest-first; exhaust the range before selecting
            # the latest N. Returning only the first page silently shows old prices.
            rows = {}
            page_key = None
            seen_keys = set()
            for _ in range(100):
                ret, data, next_key = ctx.request_history_kline(**kwargs, page_req_key=page_key)
                if ret != RET_OK:
                    if is_history_quota_error(data):
                        raise HistoricalCandleQuotaError(str(data))
                    raise RuntimeError(str(data))
                for _, row in data.iterrows():
                    if row.get("code") is not None and str(row.get("code")) != symbol:
                        raise RuntimeError("Broker candle symbol does not match request")
                    rows[str(row.get("time_key"))] = row
                if not next_key:
                    break
                marker = repr(next_key)
                if marker in seen_keys:
                    raise RuntimeError("Broker repeated a candle pagination key")
                seen_keys.add(marker)
                page_key = next_key
            else:
                raise RuntimeError("Candle history pagination exceeded the safety limit")

            candles = []

            eligible_times = [key for key in sorted(rows) if not before or key < before]
            for time_key in eligible_times[-count:]:
                row = rows[time_key]
                candle_time = datetime.fromisoformat(time_key).replace(tzinfo=ZoneInfo(market_timezone))
                candles.append({
                    "timestamp": int(candle_time.timestamp()),
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
                "timezone": market_timezone,
                "adjustment": adjustment_key,
                "session": "REGULAR",
                "start": kwargs["start"],
                "end": kwargs["end"],
                "latest_candle_time": candles[-1]["time"] if candles else None,
                "before": before,
                "oldest_candle_time": candles[0]["time"] if candles else None,
                "has_more": bool(candles),
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


    def _load_symbol_catalog(self, market_id, market_enum, security_type):
        ctx = self._context()
        try:
            ret, data = ctx.get_stock_basicinfo(market_enum, security_type)
            if ret != RET_OK:
                raise RuntimeError(str(data))
            entries = []
            for row in data.to_dict("records"):
                code = str(row.get("code") or "")
                if not code:
                    continue
                ticker = code.split(".", 1)[-1]
                name = str(row.get("name") or "")
                entries.append({"symbol": code, "ticker": ticker, "name": name,
                                "market": market_id, "security_type": str(security_type),
                                "_ticker": ticker.lower(), "_name": name.lower()})
            return entries
        finally:
            ctx.close()

    def search_symbols(self, query: str, markets: list[str] | None = None, limit: int = 20):
        query = query.strip().lower()
        if not query:
            return []
        market_map = {"US": Market.US, "HK": Market.HK, "SH": Market.SH, "SZ": Market.SZ,
                      "SG": Market.SG, "MY": Market.MY, "JP": Market.JP}
        selected = list(dict.fromkeys(m.upper() for m in (markets or market_map) if m.upper() in market_map))
        prefix, separator, remainder = query.partition(".")
        if separator and prefix.upper() in market_map:
            selected = [m for m in selected if m == prefix.upper()]
            query = remainder
        if not query:
            return []

        matches = {}
        loaded = 0
        waiting = False
        deadline = time.monotonic() + 8
        for market_id in selected:
            for security_type in (SecurityType.STOCK, SecurityType.ETF):
                try:
                    catalog = self._symbol_catalog.get(
                        (market_id, str(security_type)),
                        lambda market_id=market_id, security_type=security_type: self._load_symbol_catalog(market_id, market_map[market_id], security_type),
                        wait_timeout=min(4, max(0, deadline - time.monotonic())))
                except SymbolCatalogTimeout:
                    waiting = True
                    continue
                except Exception:
                    # Unsupported combinations are retried after a short backoff.
                    continue
                loaded += 1
                for item in catalog:
                    ticker, name = item['_ticker'], item['_name']
                    if ticker == query: score = 0
                    elif name == query: score = 1
                    elif ticker.startswith(query): score = 2
                    elif name.startswith(query): score = 3
                    elif query in ticker: score = 4
                    elif query in name: score = 5
                    else: continue
                    if item['symbol'] not in matches or score < matches[item['symbol']]['_score']:
                        matches[item['symbol']] = {**item, '_score': score}
        if selected and not loaded:
            if waiting:
                raise SymbolCatalogTimeout("OpenD securities list is still loading. Try searching again shortly.")
            raise RuntimeError("OpenD symbol catalog is unavailable; retry shortly")
        ordered = sorted(matches.values(), key=lambda item: (item['_score'], item['market'], len(item['ticker']), item['ticker']))
        return [{key: value for key, value in item.items() if not key.startswith('_')} for item in ordered[:limit]]


opend = OpenDClient(
    host=config["moomoo"]["host"],
    port=config["moomoo"]["port"],
    default_market=config[
        "market_data"
    ]["default_market"]
)
