from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.market_history import (
    market_history
)


class MarketSeries:

    ACTIVE_STATES = {
        "MORNING",
        "AFTERNOON",
        "OPEN",
        "TRADING",
    }

    def build(
        self,
        symbol,
        snapshot=None,
        market_state=None,
        minimum_bars=300
    ):
        #
        # Ensure completed historical
        # bars exist locally.
        #
        sync = (
            market_history.ensure_history(
                symbol,
                minimum_bars=minimum_bars,
                fetch_count=500
            )
        )

        bars = (
            market_history.get(
                symbol,
                limit=500
            )
        )

        provisional = None

        state = str(
            market_state or ""
        ).upper()

        #
        # Only form a developing daily
        # candle during the regular session.
        #
        if (
            snapshot
            and self._regular_session(
                state
            )
        ):
            provisional = (
                self._snapshot_candle(
                    snapshot
                )
            )

            if provisional:
                bars.append(
                    provisional
                )

        return {
            "symbol":
                symbol,

            "history_sync":
                sync,

            "completed_bars":
                len(
                    bars
                )
                - (
                    1
                    if provisional
                    else 0
                ),

            "has_live_bar":
                provisional
                is not None,

            "live_bar":
                provisional,

            "bars":
                bars,
        }

    def _regular_session(
        self,
        state
    ):
        if not state:
            return False

        #
        # Moomoo market-state naming can
        # differ somewhat by market/version.
        #
        return (
            state in self.ACTIVE_STATES
            or "MORNING" in state
            or "AFTERNOON" in state
        )

    def _snapshot_candle(
        self,
        snapshot
    ):
        close = self._num(
            snapshot.get(
                "last_price"
            )
            or snapshot.get(
                "price"
            )
        )

        if close is None:
            return None

        now_ny = datetime.now(
            ZoneInfo(
                "America/New_York"
            )
        )

        return {
            "trade_date":
                int(
                    now_ny.strftime(
                        "%Y%m%d"
                    )
                ),

            "open":
                self._num(
                    snapshot.get(
                        "open_price"
                    )
                    or snapshot.get(
                        "open"
                    )
                ),

            "high":
                self._num(
                    snapshot.get(
                        "high_price"
                    )
                    or snapshot.get(
                        "high"
                    )
                ),

            "low":
                self._num(
                    snapshot.get(
                        "low_price"
                    )
                    or snapshot.get(
                        "low"
                    )
                ),

            #
            # Current last trade acts as
            # provisional current close.
            #
            "close":
                close,

            "volume":
                self._int(
                    snapshot.get(
                        "volume"
                    )
                ),

            "provisional":
                True,
        }

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


market_series = MarketSeries()
