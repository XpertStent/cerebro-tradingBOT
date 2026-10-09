"""Historical workflow telemetry with fake feeds; no broker or AI requests."""
import ast
import threading
import unittest
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "app/services"


def load_class(filename, name, namespace):
    node = next(n for n in ast.parse((ROOT / filename).read_text()).body if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class WorkflowHistoryTests(unittest.TestCase):
    def setUp(self):
        definitions = next(n.value for n in ast.parse((ROOT / "settings.py").read_text()).body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFINITIONS")
        values = {key: item["default"] for key, item in ast.literal_eval(definitions).items()}
        settings = SimpleNamespace(get=values.get, get_bool=lambda key: bool(values.get(key)))
        self.config = {"provider": "alpaca", "feed": "sip", "adjustment": "all", "delay_minutes": 15}
        market_data = Mock()
        market_data.configuration.return_value = self.config
        market_data.metrics_current.return_value = True
        universe = Mock()
        universe.refresh.return_value = {"eligible": {"US.TEST": {}}, "source": "FAKE", "eligible_count": 1, "sources": []}
        discovery = Mock()
        discovery.run.return_value = {"candidates": [{"symbol": "US.TEST"}], "screens": [], "snapshot_eligible": 1, "discovered_unique": 1, "selected": 1}
        opend = Mock()
        opend.get_market_states.return_value = [{"id": "US", "state": "CLOSED"}]
        self.series = Mock()
        self.metrics = Mock()
        trading = Mock()
        trading.get_account_summary.side_effect = RuntimeError("No account in test")
        namespace = dict(mean=mean, datetime=datetime, ZoneInfo=ZoneInfo, monotonic=monotonic, settings=settings,
                         market_data=market_data, universe_service=universe, local_discovery=discovery, opend=opend,
                         market_series=self.series, market_metrics=self.metrics, trading=trading,
                         HistoryQuotaReserved=type("HistoryQuotaReserved", (RuntimeError,), {}))
        self.screener = load_class("quant_screener.py", "QuantScreener", namespace)()
        self.screener._batched_snapshots = Mock(return_value=({"US.SPY": {}, "US.TEST": {}}, []))
        self.history = {**self.config, "source": "CACHE", "count": 500, "bars": 499, "requested_count": 500,
                        "fetched_count": 0, "saved_count": 0, "fresh": True, "usable": True,
                        "latest_candle_time": "2026-10-08 00:00:00", "latest_completed_candle_time": "2026-10-07 00:00:00",
                        "oldest_completed_candle_time": "2024-10-01 00:00:00", "expected_complete_date": 20261007}
        self.series.build.return_value = {"history_sync": self.history, "bars": [{}] * 499}
        self.good_metrics = {"available": True, "price": 100, "bars": 499, "median_turnover_60d": 100000000,
                             "return_20d_pct": 3.5, "discontinuity_events": [{"date": "2026-09-01", "return_pct": 40}]}
        self.metrics.build.return_value = self.good_metrics
        manager_ns = dict(threading=threading, uuid=uuid, deepcopy=deepcopy, datetime=datetime, timezone=timezone)
        self.manager = load_class("ai_decision_jobs.py", "AIDecisionJobManager", manager_ns)()
        self.manager._jobs["test"] = {"events": [], "quant": {}, "ai": {}}
        self.updates = []

    def callback(self, **values):
        self.updates.append(deepcopy(values))
        self.manager._quant_progress("test", **values)

    def test_same_inline_event_updates_with_actual_counts_and_benchmark(self):
        self.screener.run(progress_callback=self.callback)
        events = self.manager.progress("test")["events"]
        self.assertEqual(len(events), 2)
        benchmark, candidate = events
        self.assertEqual(benchmark["details"]["role"], "BENCHMARK")
        detail = candidate["details"]
        self.assertEqual(candidate["id"], "history:CANDIDATE:US.TEST")
        self.assertEqual((detail["status"], detail["fetched_count"], detail["returned_count"], detail["completed_count"], detail["analysed_count"]), ("ANALYSED", 0, 500, 499, 499))
        self.assertEqual(detail["latest_completed_candle_time"], "2026-10-07 00:00:00")
        self.assertEqual(detail["indicators"]["return_20d_pct"], 3.5)
        starts = [v["history_analysis"] for v in self.updates if v.get("history_analysis", {}).get("status") == "RUNNING"]
        self.assertEqual(len(starts), 2)
        self.assertIsNone(starts[1]["fetched_count"])
        # API callers cannot mutate the retained diagnostics.
        detail["status"] = "CHANGED"
        self.assertEqual(self.manager.progress("test")["events"][-1]["details"]["status"], "ANALYSED")

    def test_stale_history_keeps_dates_and_counts_without_analysing(self):
        unavailable = ValueError("STALE_HISTORY: current history required")
        unavailable.history_sync = {**self.history, "fresh": False, "usable": False,
                                    "refresh_error": {"message": "Provider unreachable"}}
        self.series.build.side_effect = [self.series.build.return_value, unavailable]
        self.screener.run(progress_callback=self.callback)
        detail = self.manager.progress("test")["events"][-1]["details"]
        self.assertEqual(detail["status"], "ERROR")
        self.assertEqual(detail["completed_count"], 499)
        self.assertEqual(detail["analysed_count"], 0)
        self.assertFalse(detail["fresh"])
        self.assertEqual(detail["refresh_error"]["message"], "Provider unreachable")
        self.assertEqual(self.metrics.build.call_count, 1)  # Benchmark only.

    def test_liquidity_rejection_preserves_completed_indicator_counts(self):
        self.metrics.build.side_effect = [self.good_metrics, {**self.good_metrics, "median_turnover_60d": 0}]
        self.screener.run(progress_callback=self.callback)
        detail = self.manager.progress("test")["events"][-1]["details"]
        self.assertEqual((detail["status"], detail["reason"], detail["analysed_count"]), ("SKIPPED", "LOW_HISTORICAL_LIQUIDITY", 499))

    def test_benchmark_failure_finishes_its_event_and_stops_candidates(self):
        self.series.build.side_effect = RuntimeError("Fake provider unavailable")
        with self.assertRaisesRegex(RuntimeError, "Fake provider unavailable"):
            self.screener.run(progress_callback=self.callback)
        events = self.manager.progress("test")["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["details"]["status"], "ERROR")
        self.metrics.build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
