"""Exact decision input capture, retry stability and failure persistence."""
import ast
import importlib.util
import json
import tempfile
import threading
import unittest
import uuid
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / "app/services"


def load_class(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text())
    nodes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class DecisionInputTests(unittest.TestCase):
    def setUp(self):
        values = {"ai.decision.model": "fake-model", "ai.decision.reasoning_effort": "medium",
                  "ai.decision.web_search_enabled": True, "ai.decision.search_context_size": "medium"}
        self.values = values
        ns = dict(json=json, deepcopy=deepcopy, datetime=datetime, timezone=timezone,
                  time=SimpleNamespace(sleep=Mock()), settings=SimpleNamespace(get=values.get, get_bool=lambda key: bool(values.get(key))),
                  is_retryable_openai_error=lambda exc: "429" in str(exc), retry_delay=lambda *args, **kwargs: (0, "TEST", None))
        for node in ast.parse((ROOT / "ai_decision.py").read_text()).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("DECISION_SCHEMA"):
                ns[node.targets[0].id] = ast.literal_eval(node.value)
        self.engine = load_class("ai_decision.py", "AIDecisionEngine", ns)()
        self.client = Mock()
        self.engine._client = Mock(return_value=self.client)
        self.context = {"run": {"generated_at": datetime(2026, 10, 9, tzinfo=timezone.utc)},
                        "portfolio": {"account": {"cash": 100}, "positions": [], "pending_orders": []},
                        "candidates": [{"symbol": "US.TEST", "research_context": {"text": "Quoted \"news\" and café"}}]}
        self.response = SimpleNamespace(output_text=json.dumps({"decisions": [{"symbol": "US.TEST", "action": "WATCH"}]}), output=[])
        spec = importlib.util.spec_from_file_location("input_store", ROOT / "latest_ai_decision.py")
        stores = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stores)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = stores.LatestAIDecisionStore(Path(self.temp.name) / "input.json")
        self.result_store = stores.LatestAIDecisionStore(Path(self.temp.name) / "result.json")
        job_ns = dict(threading=threading, uuid=uuid, deepcopy=deepcopy, datetime=datetime, timezone=timezone,
                      latest_decision_input=self.store, latest_ai_decision=self.result_store, resolution_lock=nullcontext)
        self.manager_type = load_class("ai_decision_jobs.py", "AIDecisionJobManager", job_ns)
        self.manager = self.manager_type()
        self.manager._jobs["run"] = {"run_id": "run", "status": "RUNNING", "ai": {}, "events": []}

    def capture(self, snapshot):
        self.manager._capture_decision_input("run", snapshot)

    def test_capture_is_the_sent_body_and_normalized_context_before_call(self):
        sent = []
        def create(**kwargs):
            captured = self.manager.decision_input("run")["snapshot"]
            self.assertEqual(captured["request"], kwargs)
            sent.append(deepcopy(kwargs))
            return self.response
        self.client.responses.create.side_effect = create
        result = self.engine.run(context=self.context, request_callback=self.capture)
        snapshot = result["request_snapshot"]
        self.assertEqual(snapshot["request"], sent[0])
        context_text = sent[0]["input"].split("\n\nCEREBRO CONTEXT:\n", 1)[1].rsplit("\n\n", 1)[0]
        self.assertEqual(json.loads(context_text), snapshot["context"])
        self.assertEqual(snapshot["request"]["text"]["format"]["type"], "json_schema")
        self.assertEqual(snapshot["request"]["tools"][0]["type"], "web_search")
        self.assertIn("Return only the requested structured result.", snapshot["instructions"])
        self.context["portfolio"]["account"]["cash"] = 999
        self.assertEqual(snapshot["context"]["portfolio"]["account"]["cash"], 100)
        self.assertNotIn("api_key", snapshot["request"])
        progress = self.manager.progress("run")
        self.assertTrue(progress["decision_input_available"])
        self.assertNotIn("decision_input", progress)
        self.assertNotIn("snapshot", progress)

    def test_retry_keeps_the_same_capture_even_when_settings_change(self):
        captured = Mock(side_effect=self.capture)
        bodies = []
        def create(**kwargs):
            bodies.append(deepcopy(kwargs))
            if len(bodies) == 1:
                self.values["ai.decision.model"] = "changed-model"
                self.values["ai.decision.web_search_enabled"] = False
                raise RuntimeError("429 test")
            return self.response
        self.client.responses.create.side_effect = create
        self.engine.run(context=self.context, request_callback=captured)
        captured.assert_called_once()
        self.assertEqual(bodies[0], bodies[1])

    def test_failed_request_survives_restart_and_never_returns_a_different_run(self):
        self.values["ai.decision.web_search_enabled"] = False
        self.client.responses.create.side_effect = RuntimeError("401 fake failure")
        with self.assertRaisesRegex(RuntimeError, "401"):
            self.engine.run(context=self.context, request_callback=self.capture)
        restored = self.manager_type()
        snapshot = restored.decision_input("run")["snapshot"]
        self.assertNotIn("tools", snapshot["request"])
        self.assertIsNone(restored.decision_input("other-run"))
        self.assertEqual(restored.latest()["status"], "INPUT_CAPTURED")
        self.manager.clear_latest()
        self.assertIsNone(restored.decision_input("run"))
        self.assertFalse(self.manager.progress("run")["decision_input_available"])

    def test_completed_result_retains_its_exact_snapshot_after_input_rotates(self):
        self.client.responses.create.return_value = self.response
        result = self.engine.run(context=self.context, request_callback=self.capture)
        self.result_store.save(run_id="run", result={"ai": result})
        self.store.save(run_id="new-run", result={"request": {"input": "other"}})
        restored = self.manager_type()
        self.assertEqual(restored.decision_input("run")["snapshot"], result["request_snapshot"])


if __name__ == "__main__":
    unittest.main()
