import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.Lock()


class StrategyStore:

    def __init__(self):
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(
            DB_PATH,
            timeout=10
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        DB_PATH.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'IDLE',
                    parameters TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

    def list(self):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM strategies
                ORDER BY id ASC
            """).fetchall()

        return [
            self._decode(row)
            for row in rows
        ]

    def get(self, strategy_id):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM strategies
                WHERE id = ?
                """,
                (strategy_id,)
            ).fetchone()

        return (
            self._decode(row)
            if row
            else None
        )

    def create(
        self,
        *,
        name,
        strategy_type,
        symbol,
        timeframe,
        parameters=None
    ):
        now = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        parameters = parameters or {}

        with _lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO strategies (
                        name,
                        strategy_type,
                        symbol,
                        timeframe,
                        enabled,
                        status,
                        parameters,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, 0, 'IDLE', ?, ?, ?)
                    """,
                    (
                        name,
                        strategy_type,
                        symbol,
                        timeframe,
                        json.dumps(parameters),
                        now,
                        now
                    )
                )

                strategy_id = cursor.lastrowid

        return self.get(strategy_id)

    def set_enabled(
        self,
        strategy_id,
        enabled
    ):
        now = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        with _lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE strategies
                    SET enabled = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        1 if enabled else 0,
                        "ENABLED"
                        if enabled
                        else "IDLE",
                        now,
                        strategy_id
                    )
                )

        return self.get(strategy_id)

    def delete(self, strategy_id):
        with _lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM strategies
                    WHERE id = ?
                    """,
                    (strategy_id,)
                )

        return cursor.rowcount > 0

    def _decode(self, row):
        data = dict(row)

        data["enabled"] = bool(
            data["enabled"]
        )

        try:
            data["parameters"] = json.loads(
                data["parameters"]
            )
        except Exception:
            data["parameters"] = {}

        return data


strategies = StrategyStore()
