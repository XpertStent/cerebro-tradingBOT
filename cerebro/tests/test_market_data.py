"""Provider/caching/freshness integration tests with synthetic feeds only."""

import ast
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app/services"


def load(name, replacements=None, omit=None):
    tree = ast.parse((ROOT / f"{name}.py").read_text())
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == omit for t in node.targets)
        )
    ]
    module = ModuleType(f"app.services.{name}")
    replacements = replacements or {}
    previous = {key: sys.modules.get(key) for key in replacements}
    try:
        sys.modules.update(replacements)
        exec(compile(tree, str(ROOT / f"{name}.py"), "exec"), module.__dict__)
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    return module


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        source = ast.parse((ROOT / "settings.py").read_text())
        defaults = ast.literal_eval(
            next(
                n.value
                for n in source.body
                if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", None) == "DEFINITIONS"
            )
        )
        self.values = {k: v.get("default") for k, v in defaults.items()}
        self.settings = SimpleNamespace(
            get=lambda key: self.values.get(key),
            get_bool=lambda key: bool(self.values.get(key)),
        )
        self.opend = Mock()
        self.opend.normalize_symbol.side_effect = lambda s: (
            s.upper()
            if s.upper().split(".")[0] in {"US", "HK", "JP", "SH", "SZ", "SG", "MY"}
            else "US." + s.upper()
        )
        self.replacements = {
            "app.services.settings": SimpleNamespace(settings=self.settings),
            "app.services.opend": SimpleNamespace(opend=self.opend),
        }
        self.sessions = load("exchange_sessions")
        self.cache_module = load("candle_cache")
        self.alpaca_module = load("alpaca_data", self.replacements)
        self.alpaca = Mock(TIMEFRAMES=self.alpaca_module.AlpacaDataClient.TIMEFRAMES)
        self.alpaca.ticker.side_effect = self.alpaca_module.AlpacaDataClient.ticker
        self.replacements.update(
            {
                "app.services.exchange_sessions": self.sessions,
                "app.services.candle_cache": self.cache_module,
                "app.services.alpaca_data": SimpleNamespace(
                    alpaca_data=self.alpaca,
                    MarketDataError=self.alpaca_module.MarketDataError,
                ),
            }
        )
        self.module = load("market_data", self.replacements, omit="market_data")
        self.now = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
        self.cache = self.cache_module.CandleCache(Path(self.temp.name) / "history.db")
        self.data = self.module.MarketDataService(self.cache, clock=lambda: self.now)
        self.replacements["app.services.market_data"] = SimpleNamespace(
            market_data=self.data
        )
        self.values.update(
            {"history.minimum_completed_bars": 60, "history.fetch_count": 100}
        )
        self.opend.get_candles.side_effect = lambda **kw: {
            "candles": self.bars(kw["count"])
        }
        self.alpaca.candles.side_effect = lambda *args, **kw: self.bars(args[2])

    def bars(self, count, price=100):
        calendar = self.sessions.calendar_for("US.TEST")
        expected = self.data.expected_date("US.TEST")
        dates = calendar.sessions_in_range("2020-01-01", expected)[-count:]
        return [
            {
                "timestamp": int(
                    datetime.combine(
                        day.date(), datetime.min.time(), ZoneInfo("America/New_York")
                    ).timestamp()
                ),
                "time": day.strftime("%Y-%m-%d 00:00:00"),
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + ((len(dates) - 1 - index) % 2) * 0.1,
                "volume": 1000,
                "turnover": 100000,
            }
            for index, day in enumerate(dates)
        ]

    def test_chart_quant_and_metrics_share_cache_and_fetch_count(self):
        chart = self.data.get_candles("US.TEST", count=50)
        self.assertTrue(chart["fresh"])
        self.assertEqual(self.opend.get_candles.call_args.kwargs["count"], 100)
        history = self.data.completed_history("US.TEST")
        self.assertTrue(history["usable"])
        self.assertEqual(history["source"], "CACHE")
        self.assertEqual(self.opend.get_candles.call_count, 1)
        metrics = load("market_metrics", self.replacements).market_metrics.build(
            "US.TEST"
        )
        self.assertTrue(metrics["available"])
        self.assertEqual(metrics["data_quality"]["adjustment"], "qfq")
        self.assertEqual(self.opend.get_candles.call_count, 1)

    def test_provider_feed_adjustment_and_delay_are_isolated_and_persist(self):
        self.data.completed_history("US.TEST")
        broker_key = self.data.key("US.TEST")
        self.values["data.provider"] = "alpaca"
        self.alpaca.candles.side_effect = lambda *args, **kw: self.bars(
            args[2], price=200
        )
        alpaca = self.data.completed_history("US.TEST")
        self.assertEqual(alpaca["candles"][-1]["close"], 200)
        self.assertEqual(alpaca["feed"], "delayed_sip")
        self.assertEqual(self.alpaca.candles.call_args.kwargs["feed"], "sip")
        self.assertEqual(self.cache.rows(broker_key)[-1]["close"], 100)
        self.values["alpaca.feed"] = "iex"
        self.data.completed_history("US.TEST")
        self.values["data.adjustment"] = "raw"
        self.data.completed_history("US.TEST")
        self.values.update(
            {
                "alpaca.feed": "sip",
                "data.adjustment": "adjusted",
                "alpaca.delay_minutes": 0,
            }
        )
        self.data.completed_history("US.TEST")
        with self.cache.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM candle_rebases").fetchone()[0], 4
            )
        reopened = self.cache_module.CandleCache(self.cache.path)
        self.assertEqual(reopened.rows(broker_key)[-1]["close"], 100)

    def test_older_chart_page_is_cached_and_cursor_exclusive(self):
        self.data.get_candles("US.TEST", count=50)
        before = self.bars(50)[0]["time"]
        cursor = self.data._cursor(before, "US.TEST")
        older = self.bars(180)[:80]
        self.opend.get_candles.side_effect = lambda **kw: {"candles": older}
        result = self.data.get_candles("US.TEST", count=40, before=before)
        self.assertTrue(all(row["timestamp"] < cursor for row in result["candles"]))
        self.assertEqual(self.opend.get_candles.call_args.kwargs["before"], before)
        calls = self.opend.get_candles.call_count
        repeat = self.data.get_candles("US.TEST", count=40, before=before)
        self.assertEqual(repeat["source"], "CACHE")
        self.assertEqual(self.opend.get_candles.call_count, calls)

    def test_full_rebase_updates_old_bars_after_next_completed_session(self):
        self.data.completed_history("US.TEST")
        old_date = self.cache.rows(self.data.key("US.TEST"))[0]["trade_date"]
        self.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
        self.opend.get_candles.side_effect = lambda **kw: {
            "candles": self.bars(kw["count"], price=50)
        }
        result = self.data.completed_history("US.TEST")
        self.assertTrue(result["usable"])
        old = [
            r
            for r in self.cache.rows(self.data.key("US.TEST"))
            if r["trade_date"] == old_date
        ][0]
        self.assertLess(old["close"], 51)
        self.assertEqual(result["last_cached_date"], 20261006)

    def test_failed_or_stale_history_is_not_usable_or_current_ai_metrics(self):
        result = self.data.completed_history("US.TEST")
        metrics = {
            "available": True,
            "data_quality": {k: v for k, v in result.items() if k != "candles"},
        }
        self.assertTrue(self.data.metrics_current("US.TEST", metrics))
        self.now += timedelta(days=1)
        self.opend.get_candles.side_effect = RuntimeError("synthetic unavailable")
        failed = self.data.completed_history("US.TEST")
        self.assertFalse(failed["usable"])
        self.assertEqual(failed["skip_reason"], "STALE_HISTORY")
        self.assertFalse(self.data.metrics_current("US.TEST", metrics))
        self.values["data.provider"] = "alpaca"
        self.assertFalse(self.data.metrics_current("US.TEST", metrics))
        self.assertFalse(self.data.metrics_current("US.TEST", {"available": True}))
        with self.assertRaises(RuntimeError):
            self.data.validate_proposal(
                {
                    "symbol": "US.TEST",
                    "market_data_configuration": {"provider": "opend"},
                    "indicator_metrics": metrics,
                }
            )

    def test_concurrent_calls_download_one_series_once(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(lambda _: self.data.completed_history("US.TEST"), range(4))
            )
        self.assertTrue(all(r["usable"] for r in results))
        self.assertEqual(self.opend.get_candles.call_count, 1)

    def test_holidays_early_close_and_post_close_same_day(self):
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST", datetime(2026, 12, 25, 23, tzinfo=timezone.utc)
            ),
            "2026-12-24",
        )
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST", datetime(2026, 11, 27, 18, 10, tzinfo=timezone.utc)
            ),
            "2026-11-25",
        )
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST", datetime(2026, 11, 27, 18, 20, tzinfo=timezone.utc)
            ),
            "2026-11-27",
        )
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST",
                datetime(2026, 11, 27, 18, 20, tzinfo=timezone.utc),
                delay_minutes=15,
            ),
            "2026-11-25",
        )
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST",
                datetime(2026, 11, 27, 23, tzinfo=timezone.utc),
                aggregate_day=True,
            ),
            "2026-11-25",
        )
        self.assertEqual(
            self.sessions.latest_completed(
                "US.TEST",
                datetime(2026, 11, 28, 6, tzinfo=timezone.utc),
                aggregate_day=True,
            ),
            "2026-11-27",
        )

    def test_hourly_aggregation_excludes_premarket_and_aligns_at_open(self):
        day = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        bars = [
            {
                "timestamp": int((day + timedelta(minutes=i)).timestamp()),
                "open": 100 + i,
                "high": 101 + i,
                "low": 99 + i,
                "close": 100 + i,
                "volume": 1,
                "turnover": 100 + i,
            }
            for i in range(151)
        ]
        result = self.sessions.aggregate_regular_minutes("US.TEST", bars, 60)
        self.assertEqual(result[0]["time"], "2026-10-05 09:30:00")
        self.assertEqual(result[0]["open"], 130)
        self.assertEqual(result[0]["close"], 189)
        self.assertEqual(result[0]["volume"], 60)
        self.assertEqual(result[1]["time"], "2026-10-05 10:30:00")

    def test_adjusted_history_rebases_at_new_ex_date_before_close(self):
        self.now = datetime(2026, 10, 5, 21, tzinfo=timezone.utc)
        self.data.completed_history("US.TEST")
        old_date = self.cache.rows(self.data.key("US.TEST"))[0]["trade_date"]
        self.now = datetime(2026, 10, 6, 14, tzinfo=timezone.utc)
        self.opend.get_candles.side_effect = lambda **kw: {
            "candles": self.bars(kw["count"], price=50)
        }
        self.data.completed_history("US.TEST")
        old = [
            r
            for r in self.cache.rows(self.data.key("US.TEST"))
            if r["trade_date"] == old_date
        ][0]
        self.assertLess(old["close"], 51)

    def test_quote_provider_and_fundamentals_remain_explicitly_separate(self):
        self.values["data.provider"] = "alpaca"
        timestamp = int(
            datetime(
                2026, 10, 6, 9, 44, tzinfo=ZoneInfo("America/New_York")
            ).timestamp()
        )
        self.alpaca.snapshots.return_value = [
            {
                "symbol": "US.TEST",
                "price": 200,
                "timestamp": timestamp,
                "provider": "alpaca",
                "feed": "delayed_sip",
            }
        ]
        self.opend.get_snapshots.return_value = [
            {
                "symbol": "US.TEST",
                "price": 100,
                "market_cap": 500000000,
                "name": "Synthetic security",
            }
        ]
        result = self.data.get_snapshots(["US.TEST"], enrich=True)[0]
        self.assertEqual(result["price"], 200)
        self.assertEqual(result["provider"], "alpaca")
        self.assertEqual(result["fundamentals_provider"], "opend")
        self.assertEqual(result["market_cap"], 500000000)

    def test_proposal_cannot_reuse_previous_session_indicators(self):
        history = self.data.completed_history("US.TEST")
        proposal = {
            "symbol": "US.TEST",
            "market_data_configuration": self.data.configuration(),
            "indicator_metrics": {
                "available": True,
                "data_quality": {k: v for k, v in history.items() if k != "candles"},
            },
        }
        self.data.validate_proposal(proposal)
        self.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
        with self.assertRaises(RuntimeError):
            self.data.validate_proposal(proposal)

    def test_trade_date_survives_into_anomaly_events(self):
        metrics = load("market_metrics", self.replacements).market_metrics
        rows = self.bars(100)
        for row in rows:
            row["trade_date"] = int(row.pop("time")[:10].replace("-", ""))
        rows[-1].update(open=200, high=201, low=199, close=200)
        result = metrics.build("US.TEST", candles=rows)
        self.assertTrue(result["discontinuity_events"])
        self.assertEqual(result["discontinuity_events"][-1]["date"], "2026-10-05")

    def test_legacy_qfq_migration_preserves_old_tables_and_tags_provider(self):
        path = Path(self.temp.name) / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.executescript(
                "CREATE TABLE securities(id INTEGER,symbol TEXT); CREATE TABLE daily_candles(security_id INTEGER,trade_date INTEGER,open REAL,high REAL,low REAL,close REAL,volume INTEGER,turnover REAL); CREATE TABLE history_metadata(key TEXT,value TEXT); INSERT INTO securities VALUES(1,'US.TEST'); INSERT INTO history_metadata VALUES('cache_version','QFQ_V2'); INSERT INTO daily_candles VALUES(1,20261005,100,101,99,100,1000,100000);"
            )
        migrated = self.cache_module.CandleCache(path)
        key = ("opend", "broker", "qfq", "REGULAR", "US.TEST", "1d")
        self.assertEqual(migrated.rows(key)[0]["provider"], "opend")
        with migrated.connect() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM daily_candles").fetchone()[0], 1
            )
        self.assertEqual(len(self.cache_module.CandleCache(path).rows(key)), 1)


class AlpacaTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "alpaca.api_key": "synthetic-key",
            "alpaca.secret_key": "synthetic-secret",
            "alpaca.requests_per_minute": 180,
        }
        self.module = load(
            "alpaca_data",
            {
                "app.services.settings": SimpleNamespace(
                    settings=SimpleNamespace(get=lambda k: self.values.get(k))
                )
            },
        )
        self.client = self.module.AlpacaDataClient()

    def test_pagination_and_corporate_action_parameters(self):
        row = {
            "t": "2026-10-05T04:00:00Z",
            "o": 100,
            "h": 101,
            "l": 99,
            "c": 100,
            "v": 10,
            "vw": 100,
            "n": 2,
        }
        self.client._request = Mock(
            side_effect=[
                {"bars": [row], "next_page_token": "next"},
                {
                    "bars": [dict(row, t="2026-10-02T04:00:00Z")],
                    "next_page_token": None,
                },
            ]
        )
        rows = self.client.candles(
            "US.TEST",
            "1d",
            100,
            start="2026-10-01",
            end="2026-10-06",
            adjustment="all",
            feed="sip",
        )
        self.assertEqual([r["trade_date"] for r in rows], [20261002, 20261005])
        params = self.client._request.call_args.args[1]
        self.assertEqual(params["adjustment"], "all")
        self.assertEqual(params["page_token"], "next")
        self.assertEqual(rows[0]["turnover"], 1000)
        with self.assertRaises(self.module.MarketDataError):
            self.client.ticker("HK.TEST")

    def test_limiter_paces_and_respects_shared_server_cooldown(self):
        moment = [0.0]
        limiter = self.module.RequestLimiter(
            clock=lambda: moment[0],
            sleep=lambda seconds: moment.__setitem__(0, moment[0] + seconds),
        )
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        self.assertAlmostEqual(moment[0], 2 * 60 / 180)
        limiter.cooldown(60)
        with self.assertRaises(self.module.MarketDataError):
            limiter.acquire()
        self.assertEqual(self.module.retry_seconds({"Retry-After": "7"}), 7)

    def test_429_cooldown_and_errors_never_echo_credentials(self):
        from urllib.error import HTTPError

        self.module.limiter = Mock()
        failure = HTTPError(
            "https://data.alpaca.markets",
            429,
            "synthetic-key",
            {"Retry-After": "60"},
            None,
        )
        with patch.dict(
            self.client._request.__globals__, urlopen=Mock(side_effect=failure)
        ):
            with self.assertRaises(self.module.MarketDataError) as caught:
                self.client._request("/v2/stocks/TEST/bars", {})
        self.assertNotIn("synthetic", str(caught.exception))
        self.assertEqual(self.module.limiter.cooldown.call_count, 3)


if __name__ == "__main__":
    unittest.main()
