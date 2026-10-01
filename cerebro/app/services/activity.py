import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.Lock()


class ActivityLog:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL,
                    action TEXT NOT NULL,
                    message TEXT NOT NULL,
                    symbol TEXT,
                    order_id TEXT,
                    details TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity(timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_category ON activity(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_level ON activity(level)")

    def write(
        self,
        *,
        category: str,
        action: str,
        message: str,
        level: str = "INFO",
        symbol: str | None = None,
        order_id: str | None = None,
        details=None,
    ):
        timestamp = datetime.now(timezone.utc).isoformat()
        if details is not None and not isinstance(details, str):
            details = json.dumps(details, ensure_ascii=False, default=str)

        with _lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO activity (
                        timestamp, category, level, action, message,
                        symbol, order_id, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        str(category or "SYSTEM").upper(),
                        str(level or "INFO").upper(),
                        str(action or "EVENT"),
                        str(message or ""),
                        symbol,
                        str(order_id) if order_id is not None else None,
                        details,
                    ),
                )
                return cursor.lastrowid

    def list(
        self,
        *,
        limit: int = 100,
        category: str | None = None,
        level: str | None = None,
        search: str | None = None,
    ):
        sql = "SELECT * FROM activity WHERE 1=1"
        params = []

        if category:
            sql += " AND category = ?"
            params.append(category.upper())
        if level:
            sql += " AND level = ?"
            params.append(level.upper())
        if search:
            q = f"%{search.strip()}%"
            sql += """
                AND (
                    category LIKE ? OR level LIKE ? OR action LIKE ?
                    OR message LIKE ? OR symbol LIKE ? OR order_id LIKE ?
                    OR details LIKE ?
                )
            """
            params.extend([q] * 7)

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


activity = ActivityLog()
