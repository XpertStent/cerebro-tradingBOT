import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.RLock()


class AIThesisStore:
    """Manage thesis history with one ACTIVE thesis per symbol.

    Older Cerebro builds used UNIQUE(symbol, status), which accidentally
    allowed only one CLOSED thesis per symbol. The migration below replaces
    that constraint with a partial unique index for ACTIVE rows only.
    """

    def __init__(self):
        self._migrate_schema()

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def _migrate_schema(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_theses'"
                ).fetchone()
                if not row:
                    return
                schema = (row["sql"] or "").replace(" ", "").lower()
                if "unique(symbol,status)" in schema:
                    conn.execute("ALTER TABLE ai_theses RENAME TO ai_theses_legacy")
                    conn.execute("""
                        CREATE TABLE ai_theses (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            symbol TEXT NOT NULL,
                            strategy TEXT,
                            status TEXT NOT NULL DEFAULT 'ACTIVE',
                            thesis TEXT NOT NULL,
                            invalidation TEXT,
                            opened_at TEXT NOT NULL,
                            last_reviewed_at TEXT NOT NULL,
                            closed_at TEXT,
                            entry_decision_id INTEGER,
                            closing_decision_id INTEGER,
                            closing_reason TEXT
                        )
                    """)
                    conn.execute("""
                        INSERT INTO ai_theses (
                            id, symbol, strategy, status, thesis, invalidation,
                            opened_at, last_reviewed_at, closed_at,
                            entry_decision_id, closing_decision_id, closing_reason
                        )
                        SELECT
                            id, symbol, strategy, status, thesis, invalidation,
                            opened_at, last_reviewed_at, closed_at,
                            entry_decision_id, closing_decision_id, closing_reason
                        FROM ai_theses_legacy
                    """)
                    conn.execute("DROP TABLE ai_theses_legacy")

                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ai_theses_symbol ON ai_theses(symbol)"
                )
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_theses_one_active
                    ON ai_theses(symbol)
                    WHERE status = 'ACTIVE'
                """)

    def replace_active(self, *, symbol, thesis, strategy=None, invalidation=None,
                       entry_decision_id=None):
        symbol = symbol.upper()
        now = self._now()
        with _lock:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE ai_theses
                    SET status='CLOSED', closed_at=?, last_reviewed_at=?,
                        closing_reason='Replaced by new thesis'
                    WHERE symbol=? AND status='ACTIVE'
                """, (now, now, symbol))
                cursor = conn.execute("""
                    INSERT INTO ai_theses (
                        symbol, strategy, status, thesis, invalidation,
                        opened_at, last_reviewed_at, entry_decision_id
                    ) VALUES (?, ?, 'ACTIVE', ?, ?, ?, ?, ?)
                """, (
                    symbol, strategy, thesis, invalidation,
                    now, now, entry_decision_id,
                ))
                row = conn.execute(
                    "SELECT * FROM ai_theses WHERE id=?", (cursor.lastrowid,)
                ).fetchone()
        return dict(row)

    def close_active(self, *, symbol, closing_decision_id=None, reason=None,
                     status="CLOSED"):
        if status not in {"CLOSED", "INVALIDATED"}:
            raise ValueError("Thesis close status must be CLOSED or INVALIDATED")
        now = self._now()
        with _lock:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE ai_theses
                    SET status=?, closed_at=?, last_reviewed_at=?,
                        closing_decision_id=?, closing_reason=?
                    WHERE symbol=? AND status='ACTIVE'
                """, (
                    status, now, now, closing_decision_id, reason,
                    symbol.upper(),
                ))


ai_theses = AIThesisStore()
