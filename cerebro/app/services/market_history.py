import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.opend import opend


class MarketHistoryStore:

    def __init__(
        self,
        path="/data/market_history.db"
    ):
        self.path = path

        self._lock = threading.Lock()

        #
        # Moomoo historical limit:
        # 60 calls / 30 sec.
        #
        # Keep deliberate headroom.
        #
        self._rate_lock = threading.Lock()
        self._last_history_call = 0.0
        self._history_interval = 0.70

        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(
            self.path,
            timeout=30
        )

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA journal_mode=WAL"
        )

        conn.execute(
            "PRAGMA synchronous=NORMAL"
        )

        return conn

    def _init_db(self):
        with self._connect() as conn:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS securities (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL UNIQUE
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_candles (
                    security_id INTEGER NOT NULL,
                    trade_date INTEGER NOT NULL,

                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL NOT NULL,
                    volume INTEGER,

                    PRIMARY KEY (
                        security_id,
                        trade_date
                    ),

                    FOREIGN KEY (
                        security_id
                    )
                    REFERENCES securities(id)
                ) WITHOUT ROWID
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_sync (
                    security_id INTEGER PRIMARY KEY,
                    last_sync_at TEXT,
                    last_complete_date INTEGER,

                    FOREIGN KEY (
                        security_id
                    )
                    REFERENCES securities(id)
                )
            """)

    def _security_id(
        self,
        symbol
    ):
        with self._connect() as conn:

            conn.execute(
                """
                INSERT OR IGNORE
                INTO securities(symbol)
                VALUES (?)
                """,
                (
                    symbol,
                )
            )

            row = conn.execute(
                """
                SELECT id
                FROM securities
                WHERE symbol = ?
                """,
                (
                    symbol,
                )
            ).fetchone()

            return row["id"]

    def get(
        self,
        symbol,
        limit=500
    ):
        security_id = (
            self._security_id(
                symbol
            )
        )

        with self._connect() as conn:

            rows = conn.execute(
                """
                SELECT
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume

                FROM daily_candles

                WHERE security_id = ?

                ORDER BY trade_date DESC

                LIMIT ?
                """,
                (
                    security_id,
                    limit
                )
            ).fetchall()

        rows = list(
            reversed(rows)
        )

        return [
            dict(row)
            for row in rows
        ]

    def count(
        self,
        symbol
    ):
        security_id = (
            self._security_id(
                symbol
            )
        )

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_candles
                WHERE security_id = ?
                """,
                (
                    security_id,
                )
            ).fetchone()

            return int(
                row["count"]
            )

    def last_date(
        self,
        symbol
    ):
        security_id = (
            self._security_id(
                symbol
            )
        )

        with self._connect() as conn:

            row = conn.execute(
                """
                SELECT MAX(trade_date) AS trade_date
                FROM daily_candles
                WHERE security_id = ?
                """,
                (
                    security_id,
                )
            ).fetchone()

        return (
            row["trade_date"]
            if row
            else None
        )

    def ensure_history(
        self,
        symbol,
        minimum_bars=300,
        fetch_count=500
    ):
        """
        Initial implementation:

        If enough history exists locally,
        don't call Moomoo again.

        Otherwise perform one rate-limited
        historical request and persist all
        completed bars returned.
        """

        existing = self.count(
            symbol
        )

        if existing >= minimum_bars:
            return {
                "symbol": symbol,
                "source": "CACHE",
                "bars": existing,
            }

        candles = (
            self._fetch_history(
                symbol,
                fetch_count
            )
        )

        stored = self._store_completed(
            symbol,
            candles
        )

        return {
            "symbol": symbol,
            "source": "MOOMOO",
            "bars_received":
                len(candles),
            "bars_stored":
                stored,
        }

    def _fetch_history(
        self,
        symbol,
        count
    ):
        with self._rate_lock:

            elapsed = (
                time.monotonic()
                - self._last_history_call
            )

            wait = (
                self._history_interval
                - elapsed
            )

            if wait > 0:
                time.sleep(
                    wait
                )

            try:
                return opend.get_candles(
                    symbol=symbol,
                    timeframe="1d",
                    count=count
                )

            except RuntimeError as exc:

                message = str(
                    exc
                ).lower()

                if (
                    "high frequency"
                    not in message
                ):
                    raise

                #
                # Let Moomoo rolling window clear.
                #
                time.sleep(
                    31
                )

                return opend.get_candles(
                    symbol=symbol,
                    timeframe="1d",
                    count=count
                )

            finally:
                self._last_history_call = (
                    time.monotonic()
                )

    def _store_completed(
        self,
        symbol,
        candles
    ):
        if isinstance(
            candles,
            dict
        ):
            candles = (
                candles.get("candles")
                or candles.get("data")
                or []
            )

        security_id = (
            self._security_id(
                symbol
            )
        )

        #
        # Current NY date.
        #
        # We deliberately do not permanently
        # store today's potentially unfinished
        # daily candle.
        #
        today_ny = (
            datetime.now(
                ZoneInfo(
                    "America/New_York"
                )
            )
            .date()
        )

        records = []

        for row in candles:

            date_value = (
                row.get("time_key")
                or row.get("date")
                or row.get("trade_date")
            )

            trade_date = (
                self._parse_date(
                    date_value
                )
            )

            if trade_date is None:
                continue

            year = (
                trade_date // 10000
            )

            month = (
                trade_date // 100
            ) % 100

            day = (
                trade_date % 100
            )

            try:
                candle_date = datetime(
                    year,
                    month,
                    day
                ).date()

            except ValueError:
                continue

            #
            # Never persist today's
            # developing daily candle.
            #
            if candle_date >= today_ny:
                continue

            close = self._num(
                row.get("close")
                or row.get(
                    "close_price"
                )
            )

            if close is None:
                continue

            records.append(
                (
                    security_id,
                    trade_date,

                    self._num(
                        row.get("open")
                        or row.get(
                            "open_price"
                        )
                    ),

                    self._num(
                        row.get("high")
                        or row.get(
                            "high_price"
                        )
                    ),

                    self._num(
                        row.get("low")
                        or row.get(
                            "low_price"
                        )
                    ),

                    close,

                    self._int(
                        row.get(
                            "volume"
                        )
                    ),
                )
            )

        if not records:
            return 0

        with self._connect() as conn:

            conn.executemany(
                """
                INSERT INTO daily_candles (
                    security_id,
                    trade_date,
                    open,
                    high,
                    low,
                    close,
                    volume
                )

                VALUES (
                    ?, ?, ?, ?, ?, ?, ?
                )

                ON CONFLICT(
                    security_id,
                    trade_date
                )

                DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
                """,
                records
            )

            conn.execute(
                """
                INSERT INTO history_sync (
                    security_id,
                    last_sync_at,
                    last_complete_date
                )

                VALUES (?, ?, ?)

                ON CONFLICT(security_id)
                DO UPDATE SET
                    last_sync_at =
                        excluded.last_sync_at,

                    last_complete_date =
                        excluded.last_complete_date
                """,
                (
                    security_id,
                    datetime.utcnow().isoformat(),
                    max(
                        r[1]
                        for r in records
                    )
                )
            )

        return len(records)

    def _parse_date(
        self,
        value
    ):
        if value is None:
            return None

        text = str(
            value
        ).strip()

        #
        # Handles:
        # 2026-09-30
        # 2026-09-30 00:00:00
        #
        text = text[:10]

        try:
            dt = datetime.strptime(
                text,
                "%Y-%m-%d"
            )

            return int(
                dt.strftime(
                    "%Y%m%d"
                )
            )

        except ValueError:
            return None

    def _num(
        self,
        value
    ):
        try:
            if value is None:
                return None

            return float(
                value
            )

        except Exception:
            return None

    def _int(
        self,
        value
    ):
        try:
            if value is None:
                return None

            return int(
                float(value)
            )

        except Exception:
            return None


market_history = MarketHistoryStore()
