import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.Lock()


class WatchlistStore:

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
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    name TEXT,
                    market TEXT,
                    source TEXT NOT NULL DEFAULT 'MANUAL',
                    status TEXT NOT NULL DEFAULT 'WATCH',
                    score REAL,
                    reason TEXT,
                    strategy_hint TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchlist_status
                ON watchlist(status)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_watchlist_source
                ON watchlist(source)
            """)

    def list(self):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM watchlist
                ORDER BY
                    CASE status
                        WHEN 'HIGH_INTEREST' THEN 1
                        WHEN 'WATCH' THEN 2
                        WHEN 'EXIT_WATCH' THEN 3
                        ELSE 4
                    END,
                    score DESC,
                    symbol ASC
            """).fetchall()

        return [
            self._decode(row)
            for row in rows
        ]

    def get(self, symbol):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM watchlist
                WHERE symbol = ?
            """, (
                symbol.upper(),
            )).fetchone()

        return (
            self._decode(row)
            if row
            else None
        )

    def upsert(
        self,
        *,
        symbol,
        name=None,
        market=None,
        source="MANUAL",
        status="WATCH",
        score=None,
        reason=None,
        strategy_hint=None,
        enabled=True
    ):
        symbol = symbol.upper()
        source = source.upper()
        status = status.upper()

        now = (
            datetime.now(timezone.utc)
            .isoformat()
        )

        with _lock:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO watchlist (
                        symbol,
                        name,
                        market,
                        source,
                        status,
                        score,
                        reason,
                        strategy_hint,
                        enabled,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                    ON CONFLICT(symbol)
                    DO UPDATE SET
                        name = COALESCE(
                            excluded.name,
                            watchlist.name
                        ),
                        market = COALESCE(
                            excluded.market,
                            watchlist.market
                        ),
                        source = excluded.source,
                        status = excluded.status,
                        score = excluded.score,
                        reason = excluded.reason,
                        strategy_hint =
                            excluded.strategy_hint,
                        enabled = excluded.enabled,
                        updated_at =
                            excluded.updated_at
                """, (
                    symbol,
                    name,
                    market,
                    source,
                    status,
                    score,
                    reason,
                    strategy_hint,
                    1 if enabled else 0,
                    now,
                    now
                ))

        return self.get(symbol)

    def delete(self, symbol):
        with _lock:
            with self._connect() as conn:
                cursor = conn.execute("""
                    DELETE FROM watchlist
                    WHERE symbol = ?
                """, (
                    symbol.upper(),
                ))

        return cursor.rowcount > 0

    def _decode(self, row):
        data = dict(row)

        data["enabled"] = bool(
            data["enabled"]
        )

        return data


watchlist = WatchlistStore()
