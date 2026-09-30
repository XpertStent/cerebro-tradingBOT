from app.services.opend import opend


class MarketMetrics:

    def build(self, symbol: str):

        candles = opend.get_candles(
            symbol=symbol,
            timeframe="1d",
            count=260
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

        closes = [
            self._f(
                row.get("close")
                or row.get("close_price")
            )
            for row in candles
        ]

        highs = [
            self._f(
                row.get("high")
                or row.get("high_price")
            )
            for row in candles
        ]

        lows = [
            self._f(
                row.get("low")
                or row.get("low_price")
            )
            for row in candles
        ]

        volumes = [
            self._f(
                row.get("volume")
            )
            for row in candles
        ]

        closes = [
            x for x in closes
            if x is not None
        ]

        if len(closes) < 20:
            return {
                "symbol": symbol,
                "available": False
            }

        price = closes[-1]

        return {
            "symbol": symbol,
            "available": True,

            "price": price,

            "return_5d_pct":
                self._return_pct(
                    closes,
                    5
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

            "rsi_14":
                self._rsi(
                    closes,
                    14
                ),

            "ema20":
                self._ema(
                    closes,
                    20
                ),

            "ema50":
                self._ema(
                    closes,
                    50
                ),

            "ema200":
                self._ema(
                    closes,
                    200
                ),

            "above_ema20":
                self._above(
                    price,
                    self._ema(
                        closes,
                        20
                    )
                ),

            "above_ema50":
                self._above(
                    price,
                    self._ema(
                        closes,
                        50
                    )
                ),

            "above_ema200":
                self._above(
                    price,
                    self._ema(
                        closes,
                        200
                    )
                ),

            "volume_ratio_20d":
                self._volume_ratio(
                    volumes
                ),

            "atr_pct":
                self._atr_pct(
                    highs,
                    lows,
                    closes,
                    14
                ),
        }

    def _f(self, value):
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

        old = values[-days - 1]

        if not old:
            return None

        return round(
            (
                values[-1] / old - 1
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

        for prev, current in zip(
            recent,
            recent[1:]
        ):
            delta = current - prev

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

    def _volume_ratio(
        self,
        volumes
    ):
        clean = [
            v for v in volumes
            if v is not None
        ]

        if len(clean) < 21:
            return None

        avg = sum(
            clean[-21:-1]
        ) / 20

        if not avg:
            return None

        return round(
            clean[-1] / avg,
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
                    (h, l, c)
                )

        if len(rows) <= period:
            return None

        tr = []

        for i in range(
            1,
            len(rows)
        ):
            high, low, _ = rows[i]
            prev_close = rows[
                i - 1
            ][2]

            tr.append(
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

        atr = sum(
            tr[-period:]
        ) / period

        price = rows[-1][2]

        if not price:
            return None

        return round(
            (
                atr / price
            ) * 100,
            3
        )

    def _above(
        self,
        price,
        value
    ):
        if (
            price is None
            or value is None
        ):
            return None

        return price > value


market_metrics = MarketMetrics()
