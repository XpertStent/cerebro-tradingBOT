import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("/data/cerebro.db")
_lock = threading.Lock()


VALID_ACTIONS = {
    "BUY",
    "ADD",
    "HOLD",
    "REDUCE",
    "SELL",
    "WATCH",
    "IGNORE",
}

VALID_EXECUTION_STATUSES = {
    "APPROVED",
    "REJECTED",
    "DEFERRED",
    "EXECUTED",
}

VALID_THESIS_STATUSES = {
    "ACTIVE",
    "CLOSED",
    "INVALIDATED",
}


class AIMemoryStore:

    def __init__(self):
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(
            DB_PATH,
            timeout=10
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self):
        return (
            datetime.now(timezone.utc)
            .isoformat()
        )

    def _init_db(self):
        DB_PATH.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with self._connect() as conn:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type TEXT NOT NULL,
                    scheduled_for TEXT,
                    model TEXT,
                    status TEXT NOT NULL DEFAULT 'CREATED',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    tokens_in INTEGER,
                    tokens_out INTEGER,
                    estimated_cost REAL,
                    notes TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    strategy TEXT,
                    confidence REAL,
                    target_allocation_pct REAL,

                    short_reason TEXT NOT NULL,
                    what_changed TEXT,
                    thesis_status TEXT,
                    invalidation TEXT,

                    execution_status TEXT,

                    rejection_code TEXT,
                    rejection_reason TEXT,

                    broker_status TEXT,
                    order_id TEXT,

                    market_context TEXT,
                    portfolio_context TEXT,
                    signals_snapshot TEXT,

                    created_at TEXT NOT NULL,

                    FOREIGN KEY(run_id)
                        REFERENCES ai_runs(id)
                )
            """)

            conn.execute("UPDATE ai_decisions SET rejection_code='CURRENT_SET_RISK_POLICY_BLOCKED' WHERE rejection_code='RISK_BLOCKED'")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_theses (
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
                    closing_reason TEXT,

                    UNIQUE(symbol, status)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_decision_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER NOT NULL,

                    horizon_days INTEGER NOT NULL,
                    reference_price REAL,
                    observed_price REAL,
                    return_pct REAL,

                    evaluated_at TEXT NOT NULL,

                    UNIQUE(
                        decision_id,
                        horizon_days
                    ),

                    FOREIGN KEY(decision_id)
                        REFERENCES ai_decisions(id)
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_ai_decisions_symbol
                ON ai_decisions(symbol)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_ai_decisions_created_at
                ON ai_decisions(created_at DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_ai_decisions_execution_status
                ON ai_decisions(execution_status)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_ai_theses_symbol
                ON ai_theses(symbol)
            """)

    def create_run(
        self,
        *,
        run_type,
        scheduled_for=None,
        model=None,
        notes=None
    ):
        now = self._now()

        with _lock:
            with self._connect() as conn:
                cursor = conn.execute("""
                    INSERT INTO ai_runs (
                        run_type,
                        scheduled_for,
                        model,
                        status,
                        started_at,
                        notes
                    )
                    VALUES (?, ?, ?, 'CREATED', ?, ?)
                """, (
                    run_type,
                    scheduled_for,
                    model,
                    now,
                    notes
                ))

                run_id = cursor.lastrowid

        return self.get_run(run_id)

    def get_run(self, run_id):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM ai_runs
                WHERE id = ?
            """, (
                run_id,
            )).fetchone()

        return dict(row) if row else None

    def list_runs(self, limit=100):
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM ai_runs
                ORDER BY id DESC
                LIMIT ?
            """, (
                limit,
            )).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def create_decision(
        self,
        *,
        symbol,
        action,
        short_reason,
        run_id=None,
        strategy=None,
        confidence=None,
        target_allocation_pct=None,
        what_changed=None,
        thesis_status=None,
        invalidation=None,
        market_context=None,
        portfolio_context=None,
        signals_snapshot=None
    ):
        action = action.upper()

        if action not in VALID_ACTIONS:
            raise ValueError(
                f"Invalid AI action: {action}"
            )

        now = self._now()

        with _lock:
            with self._connect() as conn:
                cursor = conn.execute("""
                    INSERT INTO ai_decisions (
                        run_id,
                        symbol,
                        action,
                        strategy,
                        confidence,
                        target_allocation_pct,
                        short_reason,
                        what_changed,
                        thesis_status,
                        invalidation,
                        market_context,
                        portfolio_context,
                        signals_snapshot,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    symbol.upper(),
                    action,
                    strategy,
                    confidence,
                    target_allocation_pct,
                    short_reason,
                    what_changed,
                    thesis_status,
                    invalidation,
                    self._json(market_context),
                    self._json(portfolio_context),
                    self._json(signals_snapshot),
                    now
                ))

                decision_id = cursor.lastrowid

        return self.get_decision(decision_id)

    def set_thesis_status(self, decision_id, status):
        with _lock, self._connect() as conn:
            conn.execute("UPDATE ai_decisions SET thesis_status=? WHERE id=?", (status, decision_id))

    def set_execution_result(
        self,
        decision_id,
        *,
        status,
        rejection_code=None,
        rejection_reason=None,
        broker_status=None,
        order_id=None
    ):
        status = status.upper()
        if rejection_code == "RISK_BLOCKED":
            rejection_code = "CURRENT_SET_RISK_POLICY_BLOCKED"

        if status not in VALID_EXECUTION_STATUSES:
            raise ValueError(
                f"Invalid execution status: {status}"
            )

        if status == "REJECTED":
            if not rejection_code:
                raise ValueError(
                    "REJECTED requires rejection_code"
                )

            if not rejection_reason:
                raise ValueError(
                    "REJECTED requires rejection_reason"
                )

        if status != "REJECTED":
            rejection_code = None
            rejection_reason = None

        with _lock:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE ai_decisions
                    SET execution_status = ?,
                        rejection_code = ?,
                        rejection_reason = ?,
                        broker_status = ?,
                        order_id = ?
                    WHERE id = ?
                """, (
                    status,
                    rejection_code,
                    rejection_reason,
                    broker_status,
                    order_id,
                    decision_id
                ))

        return self.get_decision(
            decision_id
        )

    def get_decision(self, decision_id):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM ai_decisions
                WHERE id = ?
            """, (
                decision_id,
            )).fetchone()

        return (
            self._decode_decision(row)
            if row
            else None
        )

    def list_decisions(
        self,
        *,
        symbol=None,
        limit=100,
        execution_status=None
    ):
        sql = """
            SELECT *
            FROM ai_decisions
            WHERE 1=1
        """

        params = []

        if symbol:
            sql += " AND symbol = ?"
            params.append(
                symbol.upper()
            )

        if execution_status:
            sql += """
                AND execution_status = ?
            """
            params.append(
                execution_status.upper()
            )

        sql += """
            ORDER BY id DESC
            LIMIT ?
        """

        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                sql,
                params
            ).fetchall()

        return [
            self._decode_decision(row)
            for row in rows
        ]

    def get_recent_rejections(
        self,
        *,
        symbol=None,
        limit=20
    ):
        sql = """
            SELECT
                id,
                run_id,
                symbol,
                action,
                strategy,
                rejection_code,
                rejection_reason,
                created_at
            FROM ai_decisions
            WHERE execution_status = 'REJECTED'
        """

        params = []

        if symbol:
            sql += " AND symbol = ?"
            params.append(
                symbol.upper()
            )

        sql += """
            ORDER BY id DESC
            LIMIT ?
        """

        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                sql,
                params
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def create_or_replace_thesis(
        self,
        *,
        symbol,
        thesis,
        strategy=None,
        invalidation=None,
        entry_decision_id=None
    ):
        symbol = symbol.upper()
        now = self._now()

        with _lock:
            with self._connect() as conn:

                conn.execute("""
                    UPDATE ai_theses
                    SET status = 'CLOSED',
                        closed_at = ?,
                        closing_reason =
                            'Replaced by new thesis'
                    WHERE symbol = ?
                      AND status = 'ACTIVE'
                """, (
                    now,
                    symbol
                ))

                cursor = conn.execute("""
                    INSERT INTO ai_theses (
                        symbol,
                        strategy,
                        status,
                        thesis,
                        invalidation,
                        opened_at,
                        last_reviewed_at,
                        entry_decision_id
                    )
                    VALUES (
                        ?, ?, 'ACTIVE',
                        ?, ?, ?, ?, ?
                    )
                """, (
                    symbol,
                    strategy,
                    thesis,
                    invalidation,
                    now,
                    now,
                    entry_decision_id
                ))

                thesis_id = cursor.lastrowid

        return self.get_thesis(
            thesis_id
        )

    def get_thesis(self, thesis_id):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM ai_theses
                WHERE id = ?
            """, (
                thesis_id,
            )).fetchone()

        return dict(row) if row else None

    def get_active_thesis(self, symbol):
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM ai_theses
                WHERE symbol = ?
                  AND status = 'ACTIVE'
                ORDER BY id DESC
                LIMIT 1
            """, (
                symbol.upper(),
            )).fetchone()

        return dict(row) if row else None

    def list_theses(
        self,
        *,
        status=None,
        limit=100
    ):
        sql = """
            SELECT *
            FROM ai_theses
            WHERE 1=1
        """

        params = []

        if status:
            sql += " AND status = ?"
            params.append(
                status.upper()
            )

        sql += """
            ORDER BY id DESC
            LIMIT ?
        """

        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                sql,
                params
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def close_thesis(
        self,
        *,
        symbol,
        closing_decision_id=None,
        closing_reason=None,
        status="CLOSED"
    ):
        status = status.upper()

        if status not in VALID_THESIS_STATUSES:
            raise ValueError(
                f"Invalid thesis status: {status}"
            )

        now = self._now()

        with _lock:
            with self._connect() as conn:
                conn.execute("""
                    UPDATE ai_theses
                    SET status = ?,
                        closed_at = ?,
                        last_reviewed_at = ?,
                        closing_decision_id = ?,
                        closing_reason = ?
                    WHERE symbol = ?
                      AND status = 'ACTIVE'
                """, (
                    status,
                    now,
                    now,
                    closing_decision_id,
                    closing_reason,
                    symbol.upper()
                ))

        return self.get_active_thesis(
            symbol
        )

    def _json(self, value):
        if value is None:
            return None

        return json.dumps(
            value,
            separators=(",", ":")
        )

    def _decode_json(self, value):
        if not value:
            return None

        try:
            return json.loads(value)
        except Exception:
            return None

    def _decode_decision(self, row):
        data = dict(row)

        data["market_context"] = (
            self._decode_json(
                data["market_context"]
            )
        )

        data["portfolio_context"] = (
            self._decode_json(
                data["portfolio_context"]
            )
        )

        data["signals_snapshot"] = (
            self._decode_json(
                data["signals_snapshot"]
            )
        )

        return data


ai_memory = AIMemoryStore()
