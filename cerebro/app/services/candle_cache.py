"""Durable provider/feed/adjustment/interval-isolated candle storage."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class CandleCache:
    def __init__(self, path="/data/market_history.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS provider_candles (
                    provider TEXT, feed TEXT, adjustment TEXT, session TEXT,
                    symbol TEXT, timeframe TEXT, timestamp INTEGER, payload TEXT NOT NULL,
                    PRIMARY KEY(provider,feed,adjustment,session,symbol,timeframe,timestamp)
                );
                CREATE TABLE IF NOT EXISTS candle_windows (
                    provider TEXT, feed TEXT, adjustment TEXT, session TEXT,
                    symbol TEXT, timeframe TEXT, cursor TEXT, fetched_at REAL,
                    requested_count INTEGER, start_ts INTEGER, end_ts INTEGER,
                    PRIMARY KEY(provider,feed,adjustment,session,symbol,timeframe,cursor)
                );
                CREATE TABLE IF NOT EXISTS candle_rebases (
                    provider TEXT, feed TEXT, adjustment TEXT, session TEXT,
                    symbol TEXT, timeframe TEXT, completed_session TEXT,
                    PRIMARY KEY(provider,feed,adjustment,session,symbol,timeframe)
                );
                CREATE TABLE IF NOT EXISTS candle_migrations (name TEXT PRIMARY KEY);
            """)
            self._migrate_legacy(conn)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _migrate_legacy(self, conn):
        if conn.execute(
            "SELECT 1 FROM candle_migrations WHERE name='legacy_qfq_v2'"
        ).fetchone():
            return
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if {"daily_candles", "securities", "history_metadata"} <= tables:
            version = conn.execute(
                "SELECT value FROM history_metadata WHERE key='cache_version'"
            ).fetchone()
            if version and version[0] == "QFQ_V2":
                for row in conn.execute(
                    "SELECT s.symbol,c.* FROM daily_candles c JOIN securities s ON s.id=c.security_id"
                ):
                    bar = dict(row)
                    symbol = bar.pop("symbol")
                    bar.pop("security_id", None)
                    date = datetime.strptime(str(bar["trade_date"]), "%Y%m%d").replace(
                        tzinfo=ZoneInfo("America/New_York")
                    )
                    bar.update(
                        time=date.strftime("%Y-%m-%d %H:%M:%S"),
                        timestamp=int(date.timestamp()),
                        provider="opend",
                        feed="broker",
                        adjustment="qfq",
                        session="REGULAR",
                    )
                    key = ("opend", "broker", "qfq", "REGULAR", symbol, "1d")
                    conn.execute(
                        "INSERT OR IGNORE INTO provider_candles VALUES(?,?,?,?,?,?,?,?)",
                        (*key, bar["timestamp"], json.dumps(bar)),
                    )
        # Legacy tables remain intact; uncertain provenance is not guessed.
        conn.execute("INSERT INTO candle_migrations VALUES('legacy_qfq_v2')")

    def rows(self, key, before=None, limit=None):
        sql = "SELECT payload FROM provider_candles WHERE provider=? AND feed=? AND adjustment=? AND session=? AND symbol=? AND timeframe=?"
        args = list(key)
        if before is not None:
            sql += " AND timestamp < ?"
            args.append(before)
        sql += " ORDER BY timestamp DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def window(self, key, cursor=""):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM candle_windows WHERE provider=? AND feed=? AND adjustment=? AND session=? AND symbol=? AND timeframe=? AND cursor=?",
                (*key, cursor),
            ).fetchone()
        return dict(row) if row else None

    def rebase_session(self, key):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT completed_session FROM candle_rebases WHERE provider=? AND feed=? AND adjustment=? AND session=? AND symbol=? AND timeframe=?",
                key,
            ).fetchone()
        return row[0] if row else None

    def store(
        self,
        key,
        bars,
        *,
        cursor,
        fetched_at,
        requested_count,
        start_ts,
        end_ts,
        rebase=None
    ):
        with self.connect() as conn:
            if rebase is not None:
                # Atomic replacement: old adjusted bars must not survive a new adjustment basis.
                conn.execute(
                    "DELETE FROM provider_candles WHERE provider=? AND feed=? AND adjustment=? AND session=? AND symbol=? AND timeframe=?",
                    key,
                )
                conn.execute(
                    "DELETE FROM candle_windows WHERE provider=? AND feed=? AND adjustment=? AND session=? AND symbol=? AND timeframe=?",
                    key,
                )
                conn.execute(
                    "INSERT OR REPLACE INTO candle_rebases VALUES(?,?,?,?,?,?,?)",
                    (*key, rebase),
                )
            conn.executemany(
                "INSERT OR REPLACE INTO provider_candles VALUES(?,?,?,?,?,?,?,?)",
                [
                    (*key, bar["timestamp"], json.dumps(bar, allow_nan=False))
                    for bar in bars
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO candle_windows VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*key, cursor, fetched_at, requested_count, start_ts, end_ts),
            )
