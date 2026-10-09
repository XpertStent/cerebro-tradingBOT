"""One selected data source for charts, history, metrics and AI/quant prices."""

import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.alpaca_data import alpaca_data, MarketDataError
from app.services.candle_cache import CandleCache
from app.services.exchange_sessions import (
    calendar_for,
    latest_completed,
    is_regular_bar,
    quote_is_current,
    adjustment_session,
    aggregate_regular_minutes,
)
from app.services.opend import opend
from app.services.settings import settings


class MarketDataService:
    def __init__(self, cache=None, clock=None):
        self.cache = cache or CandleCache()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._series_locks = {}
        self._broker_rate_lock = threading.Lock()
        self._last_broker_request = 0.0

    def configuration(self):
        provider = settings.get("data.provider")
        adjusted = settings.get("data.adjustment") == "adjusted"
        feed = settings.get("alpaca.feed") if provider == "alpaca" else "broker"
        adjustment = (
            ("all" if provider == "alpaca" else "qfq")
            if adjusted
            else ("raw" if provider == "alpaca" else "none")
        )
        delay = (
            int(settings.get("alpaca.delay_minutes"))
            if provider == "alpaca" and feed == "sip"
            else 0
        )
        return {
            "provider": provider,
            "feed": feed,
            "adjustment": adjustment,
            "delay_minutes": delay,
        }

    def key(self, symbol, timeframe="1d", cfg=None):
        cfg = cfg or self.configuration()
        # Alpaca native daily/weekly aggregates include all eligible sessions.
        session = (
            "PROVIDER_AGGREGATE"
            if cfg["provider"] == "alpaca" and timeframe in {"1d", "1w"}
            else "REGULAR"
        )
        feed = (
            "delayed_sip"
            if cfg["provider"] == "alpaca"
            and cfg["feed"] == "sip"
            and cfg["delay_minutes"]
            else cfg["feed"]
        )
        return (
            cfg["provider"],
            feed,
            cfg["adjustment"],
            session,
            opend.normalize_symbol(symbol),
            timeframe,
        )

    def provenance(self, symbol, timeframe="1d"):
        key = self.key(symbol, timeframe)
        return dict(
            zip(
                ("provider", "feed", "adjustment", "session", "symbol", "timeframe"),
                key,
            )
        ) | {"delay_minutes": self.configuration()["delay_minutes"]}

    def expected_date(self, symbol):
        cfg = self.configuration()
        return latest_completed(
            opend.normalize_symbol(symbol),
            self.clock(),
            delay_minutes=cfg["delay_minutes"],
            aggregate_day=cfg["provider"] == "alpaca",
        )

    def _cursor(self, value, symbol):
        if value is None:
            return None
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=calendar_for(symbol).tz)
        return int(dt.timestamp())

    def _series_lock(self, key):
        with self._lock:
            return self._series_locks.setdefault(key, threading.RLock())

    def _fetch(self, key, count, start, end, automatic):
        provider, feed, adjustment, session, symbol, timeframe = key
        if provider == "alpaca":
            # Native hourly buckets start on the hour and can mix premarket
            # trades into the opening bar. Aggregate regular-session minutes.
            bars = alpaca_data.candles(
                symbol,
                "1m" if timeframe == "60m" else timeframe,
                count * 60 if timeframe == "60m" else count,
                start=start.isoformat(),
                end=end.isoformat(),
                adjustment=adjustment,
                feed="sip" if feed == "delayed_sip" else feed,
            )
            return (
                aggregate_regular_minutes(symbol, bars, 60)
                if timeframe == "60m"
                else bars
            )
        with self._broker_rate_lock:
            wait = 0.7 - (time.monotonic() - self._last_broker_request)
            if wait > 0:
                time.sleep(wait)
            try:
                if automatic:
                    opend.check_history_capacity(
                        symbol, reserve=int(settings.get("history.chart_quota_reserve"))
                    )
                data = opend.get_candles(
                    symbol=symbol,
                    timeframe=timeframe,
                    count=count,
                    start=start.astimezone(calendar_for(symbol).tz).strftime(
                        "%Y-%m-%d"
                    ),
                    end=end.astimezone(calendar_for(symbol).tz).strftime("%Y-%m-%d"),
                    adjustment=adjustment,
                    before=(end + timedelta(seconds=1))
                    .astimezone(calendar_for(symbol).tz)
                    .strftime("%Y-%m-%d %H:%M:%S"),
                )
                return data["candles"]
            finally:
                self._last_broker_request = time.monotonic()

    def get_candles(
        self, symbol, timeframe="1d", count=None, before=None, automatic=False
    ):
        symbol = opend.normalize_symbol(symbol)
        if timeframe not in alpaca_data.TIMEFRAMES:
            raise ValueError("Unsupported candle interval.")
        count = (
            int(settings.get("history.fetch_count")) if count is None else int(count)
        )
        if count < 1:
            raise ValueError("Candle count must be positive.")
        cfg = self.configuration()
        key = self.key(symbol, timeframe, cfg)
        with self._series_lock(key):
            metadata = dict(
                zip(
                    (
                        "provider",
                        "feed",
                        "adjustment",
                        "session",
                        "symbol",
                        "timeframe",
                    ),
                    key,
                )
            ) | {"delay_minutes": cfg["delay_minutes"]}
            if cfg["provider"] == "alpaca":
                alpaca_data.ticker(symbol)
            now = self.clock()
            expected = latest_completed(
                symbol,
                now,
                delay_minutes=cfg["delay_minutes"],
                aggregate_day=cfg["provider"] == "alpaca",
            )
            # Rebase both at the new trading date (ex-date adjustments) and
            # when that session completes (final provider revisions).
            basis = adjustment_session(symbol, now) + "/" + expected
            cursor_ts = self._cursor(before, symbol)
            cursor = str(cursor_ts) if cursor_ts is not None else ""
            cached = self.cache.rows(key)
            window = self.cache.window(key, cursor)
            adjusted = cfg["adjustment"] in {"all", "qfq"}
            rebase = adjusted and self.cache.rebase_session(key) != basis
            ttl = 86400 if before else int(settings.get("data.cache_ttl_seconds"))
            reusable = (
                window
                and window["requested_count"] >= count
                and now.timestamp() - window["fetched_at"] < ttl
            )
            # Daily chart and quant share the same root window and adjustment basis.
            source, failure = "CACHE", None
            fetched_count = cached_count = 0
            if not reusable or rebase:
                effective = now - timedelta(
                    minutes=cfg["delay_minutes"],
                    seconds=60 if cfg["delay_minutes"] else 0,
                )
                end = (
                    min(effective, datetime.fromtimestamp(cursor_ts - 1, timezone.utc))
                    if cursor_ts is not None
                    else effective
                )
                fetch_count = (
                    max(count, int(settings.get("history.fetch_count")))
                    if timeframe == "1d"
                    else count
                )
                minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
                days = max(
                    7, int(fetch_count * minutes.get(timeframe, 390) / 390 * 3) + 14
                )
                if timeframe == "1w":
                    days = fetch_count * 14 + 14
                start = end - timedelta(days=days)
                if rebase and cached:
                    start = min(
                        start,
                        datetime.fromtimestamp(cached[0]["timestamp"], timezone.utc),
                    )
                    end = effective
                    fetch_count = max(fetch_count, len(cached) + count)
                try:
                    bars = self._fetch(key, fetch_count, start, end, automatic)
                    fetched_count = len(bars)
                    clean = []
                    for row in bars:
                        bar = dict(row)
                        timestamp = bar.get("timestamp") or self._cursor(
                            bar.get("time"), symbol
                        )
                        if timestamp is None or not (
                            start.timestamp() <= timestamp <= end.timestamp()
                        ):
                            continue
                        if timeframe not in {"1d", "1w"} and not is_regular_bar(
                            symbol, timestamp
                        ):
                            continue
                        local = datetime.fromtimestamp(
                            timestamp, calendar_for(symbol).tz
                        )
                        bar.update(
                            timestamp=int(timestamp),
                            time=local.strftime("%Y-%m-%d %H:%M:%S"),
                            trade_date=int(local.strftime("%Y%m%d")),
                            **metadata
                        )
                        bar["adjustment_basis"] = basis if adjusted else "raw"
                        bar["completed"] = int(local.strftime("%Y%m%d")) <= int(
                            expected.replace("-", "")
                        )
                        clean.append(bar)
                    self.cache.store(
                        key,
                        clean,
                        cursor=cursor,
                        fetched_at=self.clock().timestamp(),
                        requested_count=fetch_count,
                        start_ts=int(start.timestamp()),
                        end_ts=int(end.timestamp()),
                        rebase=basis if rebase else None,
                    )
                    cached_count = len(clean)
                    cached = self.cache.rows(key)
                    window = self.cache.window(key, cursor)
                    source = cfg["provider"].upper()
                except Exception as exc:
                    if not cached:
                        raise
                    failure = {
                        "code": getattr(exc, "code", "MARKET_DATA_REFRESH_FAILED"),
                        "message": str(exc),
                    }
            eligible = [
                bar
                for bar in cached
                if cursor_ts is None or bar["timestamp"] < cursor_ts
            ]
            rows = eligible[-count:]
            completed = [
                bar
                for bar in cached
                if str(bar["trade_date"]) <= expected.replace("-", "")
            ]
            latest_date = str(completed[-1]["trade_date"]) if completed else None
            fresh = not failure and not (
                adjusted and self.cache.rebase_session(key) != basis
            )
            if timeframe == "1d":
                fresh = fresh and latest_date == expected.replace("-", "")
            elif timeframe == "1w":
                expected_week = datetime.fromisoformat(expected).date()
                expected_week -= timedelta(days=expected_week.weekday())
                latest_week = (
                    datetime.fromtimestamp(
                        cached[-1]["timestamp"], calendar_for(symbol).tz
                    ).date()
                    if cached
                    else None
                )
                fresh = (
                    fresh and latest_week is not None and latest_week >= expected_week
                )
            else:
                effective = now - timedelta(minutes=cfg["delay_minutes"])
                last_end = (
                    min(
                        cached[-1]["timestamp"] + int(timeframe[:-1]) * 60,
                        int(effective.timestamp()),
                    )
                    if cached
                    else None
                )
                fresh = fresh and quote_is_current(
                    symbol, last_end, now, cfg["delay_minutes"]
                )
            return {
                **metadata,
                "timezone": str(calendar_for(symbol).tz),
                "daily_completion": (
                    "NY calendar-day end, delay and finalization grace"
                    if cfg["provider"] == "alpaca"
                    else "Exchange close and finalization grace"
                ),
                "adjustment_basis": (
                    self.cache.rebase_session(key) if adjusted else "raw"
                ),
                "count": len(rows),
                "requested_count": count,
                "fetched_count": fetched_count,
                "saved_count": cached_count,
                "candles": rows,
                "source": source,
                "fresh": bool(fresh),
                "expected_complete_date": int(expected.replace("-", "")),
                "last_cached_date": int(latest_date) if latest_date else None,
                "last_sync_at": (
                    datetime.fromtimestamp(
                        window["fetched_at"], timezone.utc
                    ).isoformat()
                    if window
                    else None
                ),
                "before": before,
                "has_more": bool(rows),
                "latest_candle_time": rows[-1]["time"] if rows else None,
                "oldest_candle_time": rows[0]["time"] if rows else None,
                "refresh_error": failure,
            }

    def completed_history(self, symbol, minimum_bars=None):
        minimum = (
            int(settings.get("history.minimum_completed_bars"))
            if minimum_bars is None
            else minimum_bars
        )
        count = max(minimum, int(settings.get("history.fetch_count")))
        result = self.get_candles(symbol, "1d", count=count, automatic=True)
        rows = [
            bar
            for bar in result["candles"]
            if bar["trade_date"] <= result["expected_complete_date"]
        ]
        # A developing current-day bar must not reduce the configured completed count.
        if len(rows) < minimum and result["count"] >= count:
            previous_fetch = result["fetched_count"]
            previous_saved = result["saved_count"]
            result = self.get_candles(symbol, "1d", count=count + 1, automatic=True)
            result["fetched_count"] += previous_fetch
            result["saved_count"] += previous_saved
            rows = [
                bar
                for bar in result["candles"]
                if bar["trade_date"] <= result["expected_complete_date"]
            ]
        result["candles"] = rows
        result["bars"] = len(rows)
        result["latest_completed_candle_time"] = rows[-1]["time"] if rows else None
        result["oldest_completed_candle_time"] = rows[0]["time"] if rows else None
        if not result["fresh"] or len(rows) < minimum:
            result["usable"] = False
            result["skip_reason"] = (
                "STALE_HISTORY" if not result["fresh"] else "INSUFFICIENT_HISTORY"
            )
        else:
            result["usable"] = True
        return result

    def metrics_current(self, symbol, metrics):
        if not symbol:
            return False
        symbol = opend.normalize_symbol(symbol)
        quality = metrics.get("data_quality") or {}
        expected = int(self.expected_date(symbol).replace("-", ""))
        current = self.provenance(symbol)
        basis_current = current["adjustment"] not in {"all", "qfq"} or quality.get(
            "adjustment_basis"
        ) == adjustment_session(symbol, self.clock()) + "/" + self.expected_date(symbol)
        return (
            metrics.get("available") is True
            and quality.get("fresh") is True
            and quality.get("usable") is True
            and quality.get("last_cached_date") == expected
            and basis_current
            and all(
                quality.get(key) == current[key]
                for key in (
                    "provider",
                    "feed",
                    "adjustment",
                    "session",
                    "delay_minutes",
                )
            )
        )

    def validate_proposal(self, proposal):
        if proposal.get("market_data_configuration") != self.configuration():
            raise RuntimeError(
                "Market-data settings changed or this proposal predates data validation. Run a new decision cycle before approving."
            )
        metrics = proposal.get("indicator_metrics")
        if metrics and not self.metrics_current(proposal.get("symbol"), metrics):
            raise RuntimeError(
                "Proposal indicators are no longer current. Run a new decision cycle before approving."
            )

    def get_snapshots(self, symbols, enrich=False):
        symbols = list(dict.fromkeys(opend.normalize_symbol(s) for s in symbols))
        cfg = self.configuration()
        if cfg["provider"] == "opend":
            return [
                {**row, "provider": "opend", "feed": "broker", "delay_minutes": 0}
                for row in opend.get_snapshots(symbols)
            ]
        rows = alpaca_data.snapshots(
            symbols, feed=cfg["feed"], delay_minutes=cfg["delay_minutes"]
        )
        fundamentals = {}
        if enrich:
            # Alpaca snapshots have no market cap/security-status fundamentals.
            fundamentals = {r["symbol"]: r for r in opend.get_snapshots(symbols)}
        for row in rows:
            row["quote_fresh"] = quote_is_current(
                row["symbol"], row.get("timestamp"), self.clock(), cfg["delay_minutes"]
            )
            if enrich:
                extra = fundamentals.get(row["symbol"], {})
                row.update(
                    {
                        k: extra.get(k)
                        for k in (
                            "name",
                            "market_cap",
                            "sec_status",
                            "equity_valid",
                            "suspension",
                            "highest52weeks_price",
                        )
                    }
                )
                row["fundamentals_provider"] = "opend"
        return rows

    def get_snapshot(self, symbol):
        rows = self.get_snapshots([symbol])
        if not rows:
            raise MarketDataError("No market snapshot was returned for this security.")
        return rows[0]


market_data = MarketDataService()
