import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class LatestAIDecisionStore:
    def __init__(self, path="/data/latest_ai_decision.json"):
        self.path = Path(path)

    def save(self, *, run_id, result):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "result": result,
        }

        fd, temp_path = tempfile.mkstemp(
            prefix="latest_ai_decision_",
            suffix=".json",
            dir=str(self.path.parent),
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            raise

        return payload

    def load(self):
        if not self.path.exists():
            return None
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def delete(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


latest_ai_decision = LatestAIDecisionStore()
latest_decision_input = LatestAIDecisionStore("/data/latest_decision_input.json")
