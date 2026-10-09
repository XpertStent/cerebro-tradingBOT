"""Research results are inspectable before the final decision request finishes."""
import ast
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / "app/services"


def load_class(filename, name, namespace):
    node = next(n for n in ast.parse((ROOT / filename).read_text()).body
                if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class LiveResearchOutputTests(unittest.TestCase):
    def setUp(self):
        self.latest = Mock()
        self.latest.load.return_value = None
        self.captured = Mock()
        self.captured.load.return_value = None
        self.manager_type = load_class("ai_decision_jobs.py", "AIDecisionJobManager", dict(
            threading=threading, time=time, uuid=uuid, deepcopy=deepcopy,
            datetime=datetime, timezone=timezone, latest_ai_decision=self.latest,
            latest_decision_input=self.captured))
        self.manager = self.manager_type()
        self.manager._jobs["run"] = {"run_id": "run", "status": "RUNNING", "ai": {}, "events": []}
        self.payload = {"symbol": "US.TEST", "status": "READY", "model": "fake-research",
                        "research": {"summary": "Synthetic finding"},
                        "sources": [{"id": "s1", "url": "https://example.com"}], "cache": "MISS"}
        self.web = Mock()
        self.web._load_cache.return_value = None
        self.batch = load_class("ai_research_batches.py", "AIResearchBatchService", dict(
            ThreadPoolExecutor=ThreadPoolExecutor, as_completed=as_completed,
            settings=SimpleNamespace(get=lambda key: 2), ai_web_research=self.web))()

    def progress(self, **values):
        self.manager._research_progress("run", **values)

    def test_completed_batch_is_available_while_another_batch_is_pending(self):
        release = threading.Event()
        observed = []
        def research(batch, index, callback):
            if index == 2:
                if not release.wait(3):
                    raise AssertionError("First batch output was not published")
            symbol = batch[0]["symbol"]
            return {symbol: {**self.payload, "symbol": symbol}}
        self.batch._research_batch_with_retry = research
        def callback(**values):
            self.progress(**values)
            if values.get("current_symbol") == "US.TEST":
                observed.append(self.manager.research_output("run", "US.TEST"))
                release.set()
        try:
            self.batch.research_many([{"symbol": "US.TEST"}, {"symbol": "US.OTHER"}], callback)
        finally:
            release.set()
        self.assertEqual(observed[0]["output"], self.payload)
        progress = self.manager.progress("run")
        self.assertTrue(progress["ai"]["research_details"]["US.TEST"]["output_available"])
        self.assertNotIn("research_outputs", progress)
        self.assertNotIn("research_outputs", self.manager.latest())
        self.assertNotIn("research", progress["ai"]["research_details"]["US.TEST"])
        observed[0]["output"]["research"]["summary"] = "Changed"
        self.assertEqual(self.manager.research_output("run", "US.TEST")["output"], self.payload)
        self.assertIsNone(self.manager.research_output("other-run", "US.TEST"))
        self.manager.clear_decision_inputs()
        self.assertIsNone(self.manager.research_output("run", "US.TEST"))
        self.assertFalse(self.manager.progress("run")["ai"]["research_details"]["US.TEST"]["output_available"])

    def test_cache_hit_and_failed_symbol_publish_their_full_output(self):
        cached = {**self.payload, "cache": "HIT"}
        self.web._load_cache.return_value = cached
        self.batch.research_many([{"symbol": "US.TEST"}], self.progress)
        self.assertEqual(self.manager.research_output("run", "us.test")["output"], cached)
        cached["research"]["summary"] = "Mutated cache"
        self.assertNotEqual(self.manager.research_output("run", "US.TEST")["output"], cached)
        failed = {"symbol": "US.FAIL", "status": "ERROR", "error": "Fake failure", "research": None, "sources": []}
        self.web._load_cache.return_value = None
        self.batch._research_batch_with_retry = lambda *args: {"US.FAIL": failed}
        self.batch.research_many([{"symbol": "US.FAIL"}], self.progress)
        self.assertEqual(self.manager.research_output("run", "US.FAIL")["output"], failed)

    def test_restart_uses_only_matching_persisted_context(self):
        context = {"candidates": [{"symbol": "US.TEST", "research_context": self.payload}]}
        self.latest.load.return_value = {"run_id": "complete", "result": {"ai": {"context": context}}}
        self.captured.load.return_value = {"run_id": "failed", "result": {"context": context}}
        restarted = self.manager_type()
        self.assertEqual(restarted.research_output("complete", "US.TEST")["output"], self.payload)
        self.assertEqual(restarted.research_output("failed", "US.TEST")["output"], self.payload)
        self.assertIsNone(restarted.research_output("different", "US.TEST"))
        self.assertIsNone(restarted.research_output("complete", "US.UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
