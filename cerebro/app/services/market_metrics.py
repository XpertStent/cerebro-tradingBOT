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

            if close is not None:
                rows.append({
                    "close": close,
                    "high": high,
                    "low": low,
                    "volume": volume
                })

        if len(rows) < 20:
            return {
                "symbol": symbol,
                "available": False
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
