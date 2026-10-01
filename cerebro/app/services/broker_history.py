"""Account-scoped OpenD history, persisted independently of Cerebro activity logs."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class BrokerHistory:
    interval = 600

    def __init__(self, path=Path("/data/cerebro.db")):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.attempts = {}
        self.failures = set()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS broker_order_history (
                    context_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    history_refreshed_at REAL, snapshot_refreshed_at REAL NOT NULL)""")
                yield conn
        finally:
            conn.close()

    def read(self, context):
        with self.connect() as conn:
            row = conn.execute("SELECT payload, history_refreshed_at, snapshot_refreshed_at FROM broker_order_history WHERE context_id=?", (context,)).fetchone()
        return {"orders": json.loads(row[0]), "history_refreshed_at": row[1], "snapshot_refreshed_at": row[2]} if row else {"orders": [], "history_refreshed_at": None, "snapshot_refreshed_at": None}

    def history(self, context, loader, force=False):
        with self.lock:
            cached = self.read(context)
            now = time.time()
            refreshed = cached["history_refreshed_at"]
            stale = refreshed is None or now - refreshed >= self.interval
            if force or (stale and now - self.attempts.get(context, 0) >= 60):
                self.attempts[context] = now
                try:
                    rows = loader()
                except Exception:
                    self.failures.add(context)
                    return cached["orders"], refreshed, True
                self.failures.discard(context)
                return rows, now, False
            return cached["orders"], refreshed, stale or context in self.failures

    def save(self, context, orders, refreshed):
        with self.lock, self.connect() as conn:
            conn.execute("""INSERT INTO broker_order_history VALUES (?, ?, ?, ?)
                ON CONFLICT(context_id) DO UPDATE SET payload=excluded.payload,
                history_refreshed_at=excluded.history_refreshed_at,
                snapshot_refreshed_at=excluded.snapshot_refreshed_at""",
                (context, json.dumps(orders), refreshed, time.time()))

    @staticmethod
    def timestamp(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


broker_history = BrokerHistory()
