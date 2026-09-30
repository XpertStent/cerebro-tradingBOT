import sqlite3
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.opend import opend


class MarketHistoryStore:

    CACHE_VERSION = "QFQ_V2"

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
                    turnover REAL,

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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS history_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(daily_candles)"
                ).fetchall()
            }

            if "turnover" not in columns:
                conn.execute(
                    "ALTER TABLE daily_candles "
                    "ADD COLUMN turnover REAL"
                )

            version_row = conn.execute(
                """
                SELECT value
                FROM history_metadata
                WHERE key = 'cache_version'
                """
            ).fetchone()

            current_version = (
                version_row["value"]
                if version_row
                else None
            )

            if current_version != self.CACHE_VERSION:
                #
                # Existing candles were RAW V1.
                # Never mix them with QFQ history.
                #
                conn.execute(
                    "DELETE FROM daily_candles"
                )
                conn.execute(
                    "DELETE FROM history_sync"
                )

                conn.execute(
                    """
                    INSERT INTO history_metadata (
                        key,
                        value
                    )
                    VALUES (
                        'cache_version',
                        ?
                    )
                    ON CONFLICT(key)
                    DO UPDATE SET
                        value = excluded.value
                    """,
                    (
                        self.CACHE_VERSION,
                    )
                )

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
                    volume,
                    turnover

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

    def _sync_info(
        self,
        symbol
    ):
        security_id = self._security_id(
            symbol
        )

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    last_sync_at,
                    last_complete_date
                FROM history_sync
                WHERE security_id = ?
                """,
                (
                    security_id,
                )
            ).fetchone()

        return (
            dict(row)
            if row
            else {}
        )

    def _previous_weekday(
        self,
        value
    ):
        while value.weekday() >= 5:
            value -= timedelta(days=1)

        return value

    def _expected_complete_date(
        self
    ):
        now_ny = datetime.now(
            ZoneInfo(
                "America/New_York"
            )
        )

        candidate = now_ny.date()

        #
        # Before 17:00 ET, today's candle is
        # deliberately treated as incomplete.
        #
        if (
            now_ny.hour < 17
            or candidate.weekday() >= 5
        ):
            candidate -= timedelta(days=1)

        candidate = (
            self._previous_weekday(
                candidate
            )
        )

        return int(
            candidate.strftime(
                "%Y%m%d"
            )
        )

    def _synced_today(
        self,
        sync
    ):
        value = sync.get(
            "last_sync_at"
        )

        if not value:
            return False

        try:
            dt = datetime.fromisoformat(
                str(value)
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=ZoneInfo("UTC")
                )

            dt_ny = dt.astimezone(
                ZoneInfo(
                    "America/New_York"
                )
            )

            return (
                dt_ny.date()
                == datetime.now(
                    ZoneInfo(
                        "America/New_York"
                    )
                ).date()
            )

        except Exception:
            return False

    def ensure_history(
        self,
        symbol,
        minimum_bars=300,
        fetch_count=500
    ):
        """
        Keep a persistent QFQ daily history cache.

        - Full fetch when history is insufficient.
        - Incremental refresh when the latest completed
          US trading session is missing.
        - Avoid repeated refresh attempts on the same
          calendar day when no newer completed bar exists.
        """

        existing = self.count(
            symbol
        )

        last_cached = self.last_date(
            symbol
        )

        expected = (
            self._expected_complete_date()
        )

        sync = self._sync_info(
            symbol
        )

        #
        # Healthy warm cache.
        #
        if (
            existing >= minimum_bars
            and last_cached is not None
            and last_cached >= expected
        ):
            return {
                "symbol": symbol,
                "source": "CACHE",
                "bars": existing,
                "last_cached_date":
                    last_cached,
                "expected_complete_date":
                    expected,
                "fresh": True,
            }

        #
        # If we already tried refreshing this symbol
        # today and no newer completed candle existed
        # (holiday/data delay), do not repeatedly hit
        # the historical API.
        #
        if (
            existing > 0
            and self._synced_today(sync)
        ):
            return {
                "symbol": symbol,
                "source": "CACHE",
                "bars": existing,
                "last_cached_date":
                    last_cached,
                "expected_complete_date":
                    expected,
                "fresh": (
                    last_cached is not None
                    and last_cached >= expected
                ),
                "refresh_attempted_today":
                    True,
            }

        #
        # Warm cache but missing a recent completed bar:
        # only fetch a small overlapping window.
        #
        if (
            existing >= minimum_bars
            and last_cached is not None
        ):
            last_text = str(
                last_cached
            )

            last_dt = datetime.strptime(
                last_text,
                "%Y%m%d"
            ).date()

            refresh_start = (
                last_dt
                - timedelta(days=10)
            )

            candles = self._fetch_history(
                symbol,
                20,
                start_date=refresh_start
            )

            stored = self._store_completed(
                symbol,
                candles
            )

            return {
                "symbol": symbol,
                "source":
                    "MOOMOO_REFRESH",
                "bars": self.count(
                    symbol
                ),
                "bars_received": len(
                    candles.get(
                        "candles",
                        []
                    )
                    if isinstance(
                        candles,
                        dict
                    )
                    else candles
                ),
                "bars_stored": stored,
                "last_cached_date":
                    self.last_date(
                        symbol
                    ),
                "expected_complete_date":
                    expected,
            }

        #
        # Cold / incomplete cache.
        #
        candles = self._fetch_history(
            symbol,
            fetch_count
        )

        stored = self._store_completed(
            symbol,
            candles
        )

        return {
            "symbol": symbol,
            "source": "MOOMOO",
            "bars_received": len(
                candles.get(
                    "candles",
                    []
                )
                if isinstance(
                    candles,
                    dict
                )
                else candles
            ),
            "bars_stored": stored,
            "last_cached_date":
                self.last_date(
                    symbol
                ),
            "expected_complete_date":
                expected,
        }

    def _fetch_history(
        self,
        symbol,
        count,
        start_date=None
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
                today = datetime.now(
                    ZoneInfo(
                        "America/New_York"
                    )
                ).date()

                #
                # Roughly 3 calendar years easily
                # covers 500 trading sessions.
                #
                start = (
                    start_date
                    if start_date is not None
                    else (
                        today
                        - timedelta(days=1100)
                    )
                )

                return opend.get_candles(
                    symbol=symbol,
                    timeframe="1d",
                    count=count,
                    start=start.strftime(
                        "%Y-%m-%d"
                    ),
                    end=today.strftime(
                        "%Y-%m-%d"
                    ),
                    adjustment="qfq"
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

                today = datetime.now(
                    ZoneInfo(
                        "America/New_York"
                    )
                ).date()

                start = (
                    start_date
                    if start_date is not None
                    else (
                        today
                        - timedelta(days=1100)
                    )
                )

                return opend.get_candles(
                    symbol=symbol,
                    timeframe="1d",
                    count=count,
                    start=start.strftime(
                        "%Y-%m-%d"
                    ),
                    end=today.strftime(
                        "%Y-%m-%d"
                    ),
                    adjustment="qfq"
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
                row.get("time")
                or row.get("time_key")
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

                    self._num(
                        row.get(
                            "turnover"
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
                    volume,
                    turnover
                )

                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?
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
                    volume = excluded.volume,
                    turnover = excluded.turnover
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
                    datetime.now(
                        ZoneInfo("UTC")
                    ).isoformat(),
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
