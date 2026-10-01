import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class LatestQuantStore:

    def __init__(
        self,
        path="/data/latest_quant.json"
    ):
        self.path = Path(path)

    def save(
        self,
        *,
        run_id,
        result
    ):
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "generated_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "result": result,
        }

        fd, temp_path = tempfile.mkstemp(
            prefix="latest_quant_",
            suffix=".json",
            dir=str(self.path.parent)
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as f:
                json.dump(
                    payload,
                    f,
                    ensure_ascii=False,
                    separators=(",", ":")
                )

                f.flush()
                os.fsync(
                    f.fileno()
                )

            os.replace(
                temp_path,
                self.path
            )

        except Exception:
            try:
                os.unlink(
                    temp_path
                )
            except FileNotFoundError:
                pass

            raise

        return payload

    def load(self):
        if not self.path.exists():
            return None

        try:
            with self.path.open(
                "r",
                encoding="utf-8"
            ) as f:
                return json.load(f)

        except (
            OSError,
            json.JSONDecodeError
        ):
            return None

    def candidates(self):
        data = self.load()

        if not data:
            return []

        result = (
            data.get("result")
            or {}
        )

        candidates = (
            result.get("candidates")
            or []
        )

        return [
            item
            for item in candidates
            if isinstance(item, dict)
        ]

    def delete(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


latest_quant = LatestQuantStore()
