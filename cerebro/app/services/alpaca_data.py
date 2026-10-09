"""Read-only Alpaca market data. No Alpaca trading endpoints are used."""

import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.services.settings import settings


class MarketDataError(RuntimeError):
    def __init__(self, message, code="MARKET_DATA_UNAVAILABLE"):
        super().__init__(message)
        self.code = code


class RequestLimiter:
    """Shared pacing and server-directed cooldown for every Alpaca request."""

    def __init__(self, clock=time.monotonic, sleep=time.sleep):
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.next_call = 0.0

    def acquire(self):
        with self.lock:
            now = self.clock()
            wait = max(0, self.next_call - now)
            # Avoid blocking UI requests behind a long provider cooldown.
            if wait > 25:
                raise MarketDataError(
                    "Alpaca rate limit cooldown is active. Try again shortly.",
                    "MARKET_DATA_RATE_LIMITED",
                )
            if wait:
                self.sleep(wait)
            rpm = min(180, max(1, int(settings.get("alpaca.requests_per_minute"))))
            self.next_call = self.clock() + 60.0 / rpm

    def cooldown(self, seconds):
        with self.lock:
            self.next_call = max(self.next_call, self.clock() + max(0, seconds))


limiter = RequestLimiter()


def retry_seconds(headers):
    value = headers.get("Retry-After")
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        if value:
            try:
                return max(0, parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError):
                pass
    try:
        return max(0, float(headers.get("X-RateLimit-Reset")) - time.time())
    except (TypeError, ValueError):
        return 60


class AlpacaDataClient:
    TIMEFRAMES = {
        "1m": "1Min",
        "5m": "5Min",
        "15m": "15Min",
        "30m": "30Min",
        "60m": "1Hour",
        "1d": "1Day",
        "1w": "1Week",
    }

    def _request(self, path, params):
        key, secret = settings.get("alpaca.api_key"), settings.get("alpaca.secret_key")
        if not key or not secret:
            raise MarketDataError(
                "Configure both Alpaca keys in Settings → API KEYS.",
                "MARKET_DATA_CREDENTIALS_REQUIRED",
            )
        request = Request(
            "https://data.alpaca.markets" + path + "?" + urlencode(params),
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )
        for attempt in range(3):
            limiter.acquire()
            try:
                with urlopen(request, timeout=20) as response:
                    payload = json.load(response)
                    if response.headers.get("X-RateLimit-Remaining") == "0":
                        limiter.cooldown(retry_seconds(response.headers))
                    return payload
            except HTTPError as exc:
                if exc.code == 429:
                    limiter.cooldown(retry_seconds(exc.headers))
                    if attempt < 2:
                        continue
                    raise MarketDataError(
                        "Alpaca rate limit reached. Try again shortly.",
                        "MARKET_DATA_RATE_LIMITED",
                    ) from None
                if exc.code in {401, 403}:
                    raise MarketDataError(
                        "Alpaca rejected market-data access. Check the keys, selected feed and subscription delay.",
                        "MARKET_DATA_ACCESS_DENIED",
                    ) from None
                if exc.code >= 500 and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise MarketDataError(
                    f"Alpaca market-data request failed (HTTP {exc.code})."
                ) from None
            except (URLError, TimeoutError, OSError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise MarketDataError(
                    "Alpaca market-data service could not be reached."
                ) from None

    @staticmethod
    def ticker(symbol):
        if not symbol.startswith("US."):
            raise MarketDataError(
                "Alpaca supports US securities here. Select OpenD for other markets.",
                "MARKET_DATA_UNSUPPORTED_MARKET",
            )
        return symbol[3:]

    @staticmethod
    def _bar(row):
        timestamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        local = timestamp.astimezone(ZoneInfo("America/New_York"))
        volume, vwap = row.get("v"), row.get("vw")
        return {
            "timestamp": int(timestamp.timestamp()),
            "time": local.strftime("%Y-%m-%d %H:%M:%S"),
            "trade_date": int(local.strftime("%Y%m%d")),
            "open": row.get("o"),
            "high": row.get("h"),
            "low": row.get("l"),
            "close": row.get("c"),
            "volume": volume,
            "turnover": (
                volume * vwap if volume is not None and vwap is not None else None
            ),
            "vwap": vwap,
            "trade_count": row.get("n"),
            "turnover_estimated": True,
        }

    def candles(self, symbol, timeframe, count, *, start, end, adjustment, feed):
        if timeframe not in self.TIMEFRAMES:
            raise ValueError("Unsupported candle interval.")
        params = {
            "timeframe": self.TIMEFRAMES[timeframe],
            "start": start,
            "end": end,
            "adjustment": adjustment,
            "feed": feed,
            "sort": "desc",
            "limit": min(10000, max(count, 1000)),
        }
        rows, tokens = {}, set()
        for _ in range(100):
            data = self._request(
                "/v2/stocks/" + quote(self.ticker(symbol), safe="") + "/bars", params
            )
            for row in data.get("bars") or []:
                bar = self._bar(row)
                rows[bar["timestamp"]] = bar
            token = data.get("next_page_token")
            if not token:
                break
            if token in tokens:
                raise MarketDataError("Alpaca repeated a history page token.")
            tokens.add(token)
            params["page_token"] = token
        else:
            raise MarketDataError(
                "Alpaca history exceeded the pagination safety limit."
            )
        return list(sorted(rows.values(), key=lambda row: row["timestamp"]))

    def snapshots(self, symbols, *, feed, delay_minutes):
        actual_feed = "delayed_sip" if feed == "sip" and delay_minutes else feed
        output = []
        for offset in range(0, len(symbols), 100):
            batch = symbols[offset : offset + 100]
            data = self._request(
                "/v2/stocks/snapshots",
                {
                    "symbols": ",".join(self.ticker(s) for s in batch),
                    "feed": actual_feed,
                },
            )
            for symbol in batch:
                row = data.get(self.ticker(symbol))
                if not row:
                    continue
                daily, previous, trade = (
                    row.get("dailyBar") or {},
                    row.get("prevDailyBar") or {},
                    row.get("latestTrade") or {},
                )
                price = trade.get("p") or daily.get("c")
                asof = trade.get("t") or daily.get("t")
                timestamp = (
                    datetime.fromisoformat(asof.replace("Z", "+00:00")).timestamp()
                    if asof
                    else None
                )
                volume, vwap = daily.get("v"), daily.get("vw")
                output.append(
                    {
                        "symbol": symbol,
                        "price": price,
                        "open": daily.get("o"),
                        "high": daily.get("h"),
                        "low": daily.get("l"),
                        "previous_close": previous.get("c"),
                        "volume": volume,
                        "turnover": (
                            volume * vwap
                            if volume is not None and vwap is not None
                            else None
                        ),
                        "turnover_estimated": True,
                        "volume_ratio": (
                            volume / previous["v"]
                            if volume is not None and previous.get("v")
                            else None
                        ),
                        "timestamp": timestamp,
                        "as_of": asof,
                        "provider": "alpaca",
                        "feed": actual_feed,
                        "delay_minutes": delay_minutes,
                        "currency": "USD",
                        "adjustment": "raw",
                    }
                )
        return output


alpaca_data = AlpacaDataClient()
