import sqlite3
import threading
from pathlib import Path

from app.services.latest_ai_decision import latest_ai_decision, latest_decision_input


DB_PATH = Path("/data/cerebro.db")
_lock = threading.RLock()


class AIHistoryResetService:
    """Destructive test-only reset for persisted AI decision memory.

    This deliberately leaves settings, watchlist, activity logs, broker orders,
    cached market history, quant artifacts and research cache untouched.
    """

    def clear_all(self):
        deleted = {}
        with _lock:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            try:
                conn.execute("BEGIN IMMEDIATE")
                for table in (
                    "ai_decision_outcomes",
                    "ai_theses",
                    "ai_decisions",
                    "ai_runs",
                ):
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not exists:
                        deleted[table] = 0
                        continue
                    count = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    conn.execute(f"DELETE FROM {table}")
                    deleted[table] = int(count)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        latest_ai_decision.delete()
        latest_decision_input.delete()
        return {
            "cleared": True,
            "deleted": deleted,
            "message": "All persisted AI decision history and theses were cleared for testing.",
        }


ai_history_reset = AIHistoryResetService()
