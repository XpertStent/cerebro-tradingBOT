import math

from app.services.opend import opend


class MarketMetrics:

    def build(
        self,
        symbol: str,
        count: int = 260,
        candles=None
    ):
        if candles is None:
            candles = opend.get_candles(
                symbol=symbol,
                timeframe="1d",
                count=count
            )

            if isinstance(candles, dict):
                candles = (
                    candles.get("candles")
                    or candles.get("data")
                    or []
                )

        if not candles:
            return {
                "symbol": symbol,
                "available": False
            }

        rows = []

        for row in candles:
            close = self._f(
                row.get("close")
                or row.get("close_price")
            )

            high = self._f(
                row.get("high")
                or row.get("high_price")
            )

            low = self._f(
                row.get("low")
                or row.get("low_price")
            )

            volume = self._f(
                row.get("volume")
            )

            turnover = self._f(
                row.get("turnover")
            )

            open_price = self._f(
                row.get("open")
                or row.get("open_price")
            )

            if close is not None:
                rows.append({
                    "date": (
                        row.get("date")
                        or row.get("time")
                        or row.get("datetime")
                        or row.get("time_key")
                    ),
                    "open": open_price,
                    "close": close,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "turnover": turnover,
                })

        if len(rows) < 60:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "INSUFFICIENT_HISTORY",
                "bars": len(rows),
            }

        recent_quality = rows[-60:]

        invalid_ohlc = 0

        for r in recent_quality:
            o = r.get("open")
            h = r.get("high")
            l = r.get("low")
            c = r.get("close")

            if (
                c is None
                or c <= 0
                or h is None
                or l is None
                or h <= 0
                or l <= 0
                or h < l
            ):
                invalid_ohlc += 1
                continue

            if (
                o is not None
                and (
                    o <= 0
                    or o > h
                    or o < l
                )
            ):
                invalid_ohlc += 1
                continue

            if c > h or c < l:
                invalid_ohlc += 1

        if invalid_ohlc > 2:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "INVALID_OHLC",
                "invalid_ohlc_bars": invalid_ohlc,
            }

        closes = [
            r["close"]
            for r in rows
        ]

        highs = [
            r["high"]
            for r in rows
        ]

        lows = [
            r["low"]
            for r in rows
        ]

        volumes = [
            r["volume"]
            for r in rows
        ]

        turnovers = [
            r.get("turnover")
            for r in rows
        ]

        #
        # Historical liquidity.
        #
        recent_turnovers = [
            value
            for value in turnovers[-60:]
            if value is not None
            and value > 0
        ]

        if recent_turnovers:
            ordered = sorted(
                recent_turnovers
            )

            middle = len(ordered) // 2

            if len(ordered) % 2:
                median_turnover_60d = (
                    ordered[middle]
                )
            else:
                median_turnover_60d = (
                    ordered[middle - 1]
                    + ordered[middle]
                ) / 2
        else:
            #
            # Fallback for legacy/missing turnover.
            #
            dollar_volume = [
                r["close"] * r["volume"]
                for r in rows[-60:]
                if (
                    r.get("close")
                    and r.get("volume")
                )
            ]

            if dollar_volume:
                ordered = sorted(
                    dollar_volume
                )
                middle = len(ordered) // 2

                if len(ordered) % 2:
                    median_turnover_60d = (
                        ordered[middle]
                    )
                else:
                    median_turnover_60d = (
                        ordered[middle - 1]
                        + ordered[middle]
                    ) / 2
            else:
                median_turnover_60d = None

        #
        # Stale-price detection.
        #
        recent_closes = closes[-21:]

        unchanged = sum(
            1
            for a, b in zip(
                recent_closes,
                recent_closes[1:]
            )
            if a == b
        )

        if unchanged >= 8:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "STALE_PRICE_SERIES",
                "unchanged_sessions_20d": unchanged,
            }

        #
        # Discontinuity diagnostics.
        #
        # QFQ should already remove normal split artifacts,
        # so an extreme move that is also many times larger
        # than the stock's typical daily move deserves review.
        #
        # These thresholds are intentionally explicit because
        # they will later become configurable in Settings.
        #
        discontinuity_abs_threshold_pct = 35.0
        discontinuity_multiple_threshold = 8.0

        daily_moves = []
        discontinuity_events = []

        for i, (a, b) in enumerate(
            zip(
                closes,
                closes[1:]
            ),
            start=1
        ):
            if a and a > 0:
                move_pct = (
                    (b / a - 1) * 100
                )

                daily_moves.append(
                    abs(move_pct)
                )

        max_abs_daily_return_pct = (
            max(daily_moves)
            if daily_moves
            else None
        )

        if daily_moves:
            ordered_moves = sorted(
                daily_moves
            )

            middle = (
                len(ordered_moves) // 2
            )

            if len(ordered_moves) % 2:
                median_abs_daily_return_pct = (
                    ordered_moves[middle]
                )
            else:
                median_abs_daily_return_pct = (
                    ordered_moves[middle - 1]
                    + ordered_moves[middle]
                ) / 2.0

            #
            # Protect against an almost-zero median creating
            # meaningless enormous multiples.
            #
            comparison_baseline = max(
                median_abs_daily_return_pct,
                0.25
            )

            max_return_multiple = (
                max_abs_daily_return_pct
                / comparison_baseline
            )

            discontinuity_count = 0

            for i, move in enumerate(
                daily_moves,
                start=1
            ):
                multiple = (
                    move
                    / comparison_baseline
                )

                if (
                    move
                    >= discontinuity_abs_threshold_pct
                    and multiple
                    >= discontinuity_multiple_threshold
                ):
                    discontinuity_count += 1

                    previous = rows[i - 1]
                    current = rows[i]

                    signed_move_pct = (
                        (
                            current["close"]
                            / previous["close"]
                        ) - 1
                    ) * 100

                    discontinuity_events.append({
                        "date":
                            current.get("date"),

                        "previous_close":
                            round(
                                previous["close"],
                                4
                            ),

                        "close":
                            round(
                                current["close"],
                                4
                            ),

                        "return_pct":
                            round(
                                signed_move_pct,
                                3
                            ),

                        "multiple":
                            round(
                                multiple,
                                3
                            ),

                        "volume":
                            current.get("volume"),

                        "turnover":
                            current.get("turnover"),
                    })
        else:
            median_abs_daily_return_pct = None
            max_return_multiple = None
            discontinuity_count = 0

        discontinuity_flag = (
            discontinuity_count > 0
        )

        if discontinuity_count >= 2:
            discontinuity_class = (
                "MULTIPLE_EXTREME_MOVES"
            )
        elif discontinuity_count == 1:
            discontinuity_class = (
                "EXTREME_MOVE"
            )
        else:
            discontinuity_class = "NONE"

        price = closes[-1]

        ema20 = self._ema(
            closes,
            20
        )

        ema50 = self._ema(
            closes,
            50
        )

        ema200 = self._ema(
            closes,
            200
        )

        return {
            "symbol": symbol,
            "available": True,

            "price":
                round(price, 4),

            "bars":
                len(rows),

            "median_turnover_60d":
                (
                    round(
                        median_turnover_60d,
                        2
                    )
                    if median_turnover_60d
                    is not None
                    else None
                ),

            "max_abs_daily_return_pct":
                (
                    round(
                        max_abs_daily_return_pct,
                        3
                    )
                    if max_abs_daily_return_pct
                    is not None
                    else None
                ),

            "median_abs_daily_return_pct":
                (
                    round(
                        median_abs_daily_return_pct,
                        3
                    )
                    if median_abs_daily_return_pct
                    is not None
                    else None
                ),

            "max_return_multiple":
                (
                    round(
                        max_return_multiple,
                        3
                    )
                    if max_return_multiple
                    is not None
                    else None
                ),

            "discontinuity_flag":
                discontinuity_flag,

            "discontinuity_class":
                discontinuity_class,

            "requires_event_review":
                discontinuity_flag,

            "discontinuity_count":
                discontinuity_count,

            "discontinuity_events":
                discontinuity_events,

            "discontinuity_abs_threshold_pct":
                discontinuity_abs_threshold_pct,

            "discontinuity_multiple_threshold":
                discontinuity_multiple_threshold,

            "unchanged_sessions_20d":
                unchanged,

            #
            # Momentum
            #
            "return_5d_pct":
                self._return_pct(
                    closes,
                    5
                ),

            "return_10d_pct":
                self._return_pct(
                    closes,
                    10
                ),

            "return_20d_pct":
                self._return_pct(
                    closes,
                    20
                ),

            "return_50d_pct":
                self._return_pct(
                    closes,
                    50
                ),

            "return_60d_pct":
                self._return_pct(
                    closes,
                    60
                ),

            "return_120d_pct":
                self._return_pct(
                    closes,
                    120
                ),

            "return_252d_pct":
                self._return_pct(
                    closes,
                    252
                ),

            #
            # Trend
            #
            "ema20":
                ema20,

            "ema50":
                ema50,

            "ema200":
                ema200,

            "above_ema20":
                self._above(
                    price,
                    ema20
                ),

            "above_ema50":
                self._above(
                    price,
                    ema50
                ),

            "above_ema200":
                self._above(
                    price,
                    ema200
                ),

            "ema20_above_50":
                self._above(
                    ema20,
                    ema50
                ),

            "ema50_above_200":
                self._above(
                    ema50,
                    ema200
                ),

            "ema20_slope_pct":
                self._ema_slope(
                    closes,
                    20,
                    5
                ),

            "ema50_slope_pct":
                self._ema_slope(
                    closes,
                    50,
                    10
                ),

            #
            # Oscillator / extension
            #
            "rsi_14":
                self._rsi(
                    closes,
                    14
                ),

            "distance_ema20_pct":
                self._distance_pct(
                    price,
                    ema20
                ),

            "distance_ema50_pct":
                self._distance_pct(
                    price,
                    ema50
                ),

            #
            # Participation
            #
            "volume_ratio_20d":
                self._volume_ratio(
                    volumes,
                    20
                ),

            "volume_ratio_50d":
                self._volume_ratio(
                    volumes,
                    50
                ),

            #
            # Volatility
            #
            "atr_pct":
                self._atr_pct(
                    highs,
                    lows,
                    closes,
                    14
                ),

            "realized_vol_20d":
                self._realized_vol(
                    closes,
                    20
                ),

            "realized_vol_60d":
                self._realized_vol(
                    closes,
                    60
                ),

            #
            # Breakout / range
            #
            "range_position_52w":
                self._range_position(
                    closes,
                    252
                ),

            "distance_20d_high_pct":
                self._distance_from_high(
                    closes,
                    20
                ),

            "distance_50d_high_pct":
                self._distance_from_high(
                    closes,
                    50
                ),

            #
            # Trend persistence
            #
            "pct_above_ema20_20d":
                self._pct_above_ema(
                    closes,
                    20,
                    20
                ),

            "pct_above_ema50_50d":
                self._pct_above_ema(
                    closes,
                    50,
                    50
                ),
        }

    def _f(
        self,
        value
    ):
        try:
            if value is None:
                return None

            return float(value)

        except Exception:
            return None

    def _return_pct(
        self,
        values,
        days
    ):
        if len(values) <= days:
            return None

        old = values[
            -days - 1
        ]

        if not old:
            return None

        return round(
            (
                values[-1] / old
                - 1
            ) * 100,
            3
        )

    def _ema(
        self,
        values,
        period
    ):
        if len(values) < period:
            return None

        k = 2 / (
            period + 1
        )

        ema = sum(
            values[:period]
        ) / period

        for value in values[
            period:
        ]:
            ema = (
                value * k
                + ema * (
                    1 - k
                )
            )

        return round(
            ema,
            4
        )

    def _ema_slope(
        self,
        values,
        period,
        lookback
    ):
        if len(values) < (
            period + lookback
        ):
            return None

        current = self._ema(
            values,
            period
        )

        past = self._ema(
            values[:-lookback],
            period
        )

        if (
            current is None
            or past is None
            or past == 0
        ):
            return None

        return round(
            (
                current / past
                - 1
            ) * 100,
            3
        )

    def _rsi(
        self,
        values,
        period=14
    ):
        if len(values) <= period:
            return None

        recent = values[
            -(period + 1):
        ]

        gains = []
        losses = []

        for previous, current in zip(
            recent,
            recent[1:]
        ):
            delta = (
                current
                - previous
            )

            gains.append(
                max(
                    delta,
                    0
                )
            )

            losses.append(
                max(
                    -delta,
                    0
                )
            )

        avg_gain = (
            sum(gains)
            / period
        )

        avg_loss = (
            sum(losses)
            / period
        )

        if avg_loss == 0:
            return 100.0

        rs = (
            avg_gain
            / avg_loss
        )

        return round(
            100 - (
                100 / (
                    1 + rs
                )
            ),
            2
        )

    def _distance_pct(
        self,
        price,
        reference
    ):
        if (
            price is None
            or reference is None
            or reference == 0
        ):
            return None

        return round(
            (
                price / reference
                - 1
            ) * 100,
            3
        )

    def _volume_ratio(
        self,
        volumes,
        period
    ):
        clean = [
            v
            for v in volumes
            if v is not None
        ]

        if len(clean) < (
            period + 1
        ):
            return None

        baseline = clean[
            -(period + 1):-1
        ]

        average = (
            sum(baseline)
            / len(baseline)
        )

        if not average:
            return None

        return round(
            clean[-1]
            / average,
            3
        )

    def _atr_pct(
        self,
        highs,
        lows,
        closes,
        period
    ):
        rows = []

        for h, l, c in zip(
            highs,
            lows,
            closes
        ):
            if (
                h is not None
                and l is not None
                and c is not None
            ):
                rows.append(
                    (
                        h,
                        l,
                        c
                    )
                )

        if len(rows) <= period:
            return None

        true_ranges = []

        for i in range(
            1,
            len(rows)
        ):
            high = rows[i][0]
            low = rows[i][1]
            prev_close = rows[
                i - 1
            ][2]

            true_ranges.append(
                max(
                    high - low,
                    abs(
                        high
                        - prev_close
                    ),
                    abs(
                        low
                        - prev_close
                    )
                )
            )

        atr = (
            sum(
                true_ranges[
                    -period:
                ]
            )
            / period
        )

        price = rows[-1][2]

        if not price:
            return None

        return round(
            (
                atr / price
            ) * 100,
            3
        )

    def _realized_vol(
        self,
        closes,
        period
    ):
        if len(closes) <= period:
            return None

        sample = closes[
            -(period + 1):
        ]

        returns = []

        for a, b in zip(
            sample,
            sample[1:]
        ):
            if a:
                returns.append(
                    math.log(
                        b / a
                    )
                )

        if len(returns) < 2:
            return None

        mean = (
            sum(returns)
            / len(returns)
        )

        variance = (
            sum(
                (
                    x - mean
                ) ** 2
                for x in returns
            )
            / (
                len(returns)
                - 1
            )
        )

        daily_std = (
            variance ** 0.5
        )

        annualized = (
            daily_std
            * math.sqrt(252)
            * 100
        )

        return round(
            annualized,
            3
        )

    def _range_position(
        self,
        closes,
        period
    ):
        sample = closes[
            -min(
                period,
                len(closes)
            ):
        ]

        if not sample:
            return None

        low = min(sample)
        high = max(sample)

        if high == low:
            return 50.0

        return round(
            (
                closes[-1] - low
            )
            / (
                high - low
            )
            * 100,
            2
        )

    def _distance_from_high(
        self,
        closes,
        period
    ):
        if len(closes) < period:
            return None

        high = max(
            closes[-period:]
        )

        if not high:
            return None

        return round(
            (
                closes[-1]
                / high
                - 1
            ) * 100,
            3
        )

    def _pct_above_ema(
        self,
        closes,
        ema_period,
        sample_period
    ):
        if len(closes) < (
            ema_period
            + sample_period
        ):
            return None

        results = []

        start = (
            len(closes)
            - sample_period
        )

        for i in range(
            start,
            len(closes)
        ):
            subset = closes[
                :i + 1
            ]

            ema = self._ema(
                subset,
                ema_period
            )

            if ema is None:
                continue

            results.append(
                1
                if closes[i] > ema
                else 0
            )

        if not results:
            return None

        return round(
            (
                sum(results)
                / len(results)
            ) * 100,
            2
        )

    def _above(
        self,
        left,
        right
    ):
        if (
            left is None
            or right is None
        ):
            return None

        return left > right


market_metrics = MarketMetrics()
