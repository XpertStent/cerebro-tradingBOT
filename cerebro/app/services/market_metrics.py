import math

from app.services.market_data import market_data
from app.services.settings import settings


class MarketMetrics:

    @staticmethod
    def _trade_date(value):
        text = str(value or "")
        if len(text) == 8 and text.isdigit():
            return f"{text[:4]}-{text[4:6]}-{text[6:]}"
        return None

    def build(
        self,
        symbol: str,
        count: int | None = None,
        candles=None,
    ):
        if count is None:
            count = 260

        if candles is None:
            history = market_data.completed_history(symbol, minimum_bars=int(settings.get("history.minimum_completed_bars")))
            if not history["usable"]:
                return {"symbol":symbol,"available":False,"skip_reason":history["skip_reason"],
                        "data_quality":{k:v for k,v in history.items() if k != "candles"}}
            result = self.build(symbol, candles=history["candles"])
            result["data_quality"] = {k:v for k,v in history.items() if k != "candles"}
            return result

        if not candles:
            return {
                "symbol": symbol,
                "available": False,
            }

        rows = []
        for row in candles:
            close = self._f(row.get("close") or row.get("close_price"))
            high = self._f(row.get("high") or row.get("high_price"))
            low = self._f(row.get("low") or row.get("low_price"))
            volume = self._f(row.get("volume"))
            turnover = self._f(row.get("turnover"))
            open_price = self._f(row.get("open") or row.get("open_price"))

            if close is not None:
                rows.append({
                    "date": (
                        self._trade_date(row.get("trade_date"))
                        or row.get("date")
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

        minimum_history = int(settings.get("metrics.minimum_history_bars"))
        if len(rows) < minimum_history:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "INSUFFICIENT_HISTORY",
                "bars": len(rows),
            }

        validation_window = min(60, len(rows))
        recent_quality = rows[-validation_window:]
        invalid_ohlc = 0

        for row in recent_quality:
            o = row.get("open")
            h = row.get("high")
            l = row.get("low")
            c = row.get("close")

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

            if o is not None and (o <= 0 or o > h or o < l):
                invalid_ohlc += 1
                continue

            if c > h or c < l:
                invalid_ohlc += 1

        max_invalid = int(settings.get("metrics.max_invalid_ohlc_bars"))
        if invalid_ohlc > max_invalid:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "INVALID_OHLC",
                "invalid_ohlc_bars": invalid_ohlc,
            }

        closes = [row["close"] for row in rows]
        highs = [row["high"] for row in rows]
        lows = [row["low"] for row in rows]
        volumes = [row["volume"] for row in rows]
        turnovers = [row.get("turnover") for row in rows]

        recent_turnovers = [
            value
            for value in turnovers[-60:]
            if value is not None and value > 0
        ]

        if recent_turnovers:
            median_turnover_60d = self._median(recent_turnovers)
        else:
            dollar_volume = [
                row["close"] * row["volume"]
                for row in rows[-60:]
                if row.get("close") and row.get("volume")
            ]
            median_turnover_60d = (
                self._median(dollar_volume)
                if dollar_volume
                else None
            )

        recent_closes = closes[-21:]
        unchanged = sum(
            1
            for a, b in zip(recent_closes, recent_closes[1:])
            if a == b
        )

        stale_threshold = int(
            settings.get("metrics.stale_unchanged_sessions")
        )
        if unchanged >= stale_threshold:
            return {
                "symbol": symbol,
                "available": False,
                "skip_reason": "STALE_PRICE_SERIES",
                "unchanged_sessions_20d": unchanged,
            }

        discontinuity_abs_threshold_pct = float(
            settings.get("metrics.discontinuity_abs_threshold_pct")
        )
        discontinuity_multiple_threshold = float(
            settings.get("metrics.discontinuity_multiple_threshold")
        )
        baseline_floor_pct = float(
            settings.get("metrics.discontinuity_baseline_floor_pct")
        )

        daily_moves = []
        discontinuity_events = []

        for a, b in zip(closes, closes[1:]):
            if a and a > 0:
                daily_moves.append(abs((b / a - 1) * 100))

        max_abs_daily_return_pct = max(daily_moves) if daily_moves else None

        if daily_moves:
            median_abs_daily_return_pct = self._median(daily_moves)
            comparison_baseline = max(
                median_abs_daily_return_pct,
                baseline_floor_pct,
            )
            max_return_multiple = (
                max_abs_daily_return_pct / comparison_baseline
            )
            discontinuity_count = 0

            for index, move in enumerate(daily_moves, start=1):
                multiple = move / comparison_baseline
                if (
                    move >= discontinuity_abs_threshold_pct
                    and multiple >= discontinuity_multiple_threshold
                ):
                    discontinuity_count += 1
                    previous = rows[index - 1]
                    current = rows[index]
                    signed_move_pct = (
                        (current["close"] / previous["close"]) - 1
                    ) * 100
                    discontinuity_events.append({
                        "date": current.get("date"),
                        "previous_close": round(previous["close"], 4),
                        "close": round(current["close"], 4),
                        "return_pct": round(signed_move_pct, 3),
                        "multiple": round(multiple, 3),
                        "volume": current.get("volume"),
                        "turnover": current.get("turnover"),
                    })
        else:
            median_abs_daily_return_pct = None
            max_return_multiple = None
            discontinuity_count = 0

        discontinuity_flag = discontinuity_count > 0
        if discontinuity_count >= 2:
            discontinuity_class = "MULTIPLE_EXTREME_MOVES"
        elif discontinuity_count == 1:
            discontinuity_class = "EXTREME_MOVE"
        else:
            discontinuity_class = "NONE"

        price = closes[-1]
        ema20 = self._ema(closes, 20)
        ema50 = self._ema(closes, 50)
        ema200 = self._ema(closes, 200)

        return {
            "symbol": symbol,
            "available": True,
            "price": round(price, 4),
            "bars": len(rows),
            "median_turnover_60d": (
                round(median_turnover_60d, 2)
                if median_turnover_60d is not None
                else None
            ),
            "max_abs_daily_return_pct": (
                round(max_abs_daily_return_pct, 3)
                if max_abs_daily_return_pct is not None
                else None
            ),
            "median_abs_daily_return_pct": (
                round(median_abs_daily_return_pct, 3)
                if median_abs_daily_return_pct is not None
                else None
            ),
            "max_return_multiple": (
                round(max_return_multiple, 3)
                if max_return_multiple is not None
                else None
            ),
            "discontinuity_flag": discontinuity_flag,
            "discontinuity_class": discontinuity_class,
            "requires_event_review": discontinuity_flag,
            "discontinuity_count": discontinuity_count,
            "discontinuity_events": discontinuity_events,
            "discontinuity_abs_threshold_pct": discontinuity_abs_threshold_pct,
            "discontinuity_multiple_threshold": discontinuity_multiple_threshold,
            "discontinuity_baseline_floor_pct": baseline_floor_pct,
            "unchanged_sessions_20d": unchanged,

            "return_5d_pct": self._return_pct(closes, 5),
            "return_10d_pct": self._return_pct(closes, 10),
            "return_20d_pct": self._return_pct(closes, 20),
            "return_50d_pct": self._return_pct(closes, 50),
            "return_60d_pct": self._return_pct(closes, 60),
            "return_120d_pct": self._return_pct(closes, 120),
            "return_252d_pct": self._return_pct(closes, 252),

            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "above_ema20": self._above(price, ema20),
            "above_ema50": self._above(price, ema50),
            "above_ema200": self._above(price, ema200),
            "ema20_above_50": self._above(ema20, ema50),
            "ema50_above_200": self._above(ema50, ema200),
            "ema20_slope_pct": self._ema_slope(closes, 20, 5),
            "ema50_slope_pct": self._ema_slope(closes, 50, 10),

            "rsi_14": self._rsi(closes, 14),
            "distance_ema20_pct": self._distance_pct(price, ema20),
            "distance_ema50_pct": self._distance_pct(price, ema50),

            "volume_ratio_20d": self._volume_ratio(volumes, 20),
            "volume_ratio_50d": self._volume_ratio(volumes, 50),

            "atr_pct": self._atr_pct(highs, lows, closes, 14),
            "realized_vol_20d": self._realized_vol(closes, 20),
            "realized_vol_60d": self._realized_vol(closes, 60),

            "range_position_52w": self._range_position(closes, 252),
            "distance_20d_high_pct": self._distance_from_high(closes, 20),
            "distance_50d_high_pct": self._distance_from_high(closes, 50),

            "pct_above_ema20_20d": self._pct_above_ema(closes, 20, 20),
            "pct_above_ema50_50d": self._pct_above_ema(closes, 50, 50),
        }

    def _median(self, values):
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    def _f(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def _return_pct(self, values, days):
        if len(values) <= days:
            return None
        old = values[-days - 1]
        if not old:
            return None
        return round((values[-1] / old - 1) * 100, 3)

    def _ema(self, values, period):
        if len(values) < period:
            return None
        k = 2 / (period + 1)
        ema = sum(values[:period]) / period
        for value in values[period:]:
            ema = value * k + ema * (1 - k)
        return round(ema, 4)

    def _ema_slope(self, values, period, lookback):
        if len(values) < period + lookback:
            return None
        current = self._ema(values, period)
        past = self._ema(values[:-lookback], period)
        if current is None or past is None or past == 0:
            return None
        return round((current / past - 1) * 100, 3)

    def _rsi(self, values, period=14):
        if len(values) <= period:
            return None

        recent = values[-(period + 1):]
        gains = []
        losses = []
        for previous, current in zip(recent, recent[1:]):
            delta = current - previous
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def _distance_pct(self, price, reference):
        if price is None or reference is None or reference == 0:
            return None
        return round((price / reference - 1) * 100, 3)

    def _volume_ratio(self, volumes, period):
        clean = [value for value in volumes if value is not None]
        if len(clean) < period + 1:
            return None
        baseline = clean[-(period + 1):-1]
        average = sum(baseline) / len(baseline)
        if not average:
            return None
        return round(clean[-1] / average, 3)

    def _atr_pct(self, highs, lows, closes, period):
        rows = [
            (high, low, close)
            for high, low, close in zip(highs, lows, closes)
            if high is not None and low is not None and close is not None
        ]
        if len(rows) <= period:
            return None

        true_ranges = []
        for index in range(1, len(rows)):
            high, low, _ = rows[index]
            prev_close = rows[index - 1][2]
            true_ranges.append(max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            ))

        atr = sum(true_ranges[-period:]) / period
        price = rows[-1][2]
        if not price:
            return None
        return round((atr / price) * 100, 3)

    def _realized_vol(self, closes, period):
        if len(closes) <= period:
            return None
        sample = closes[-(period + 1):]
        returns = [
            math.log(b / a)
            for a, b in zip(sample, sample[1:])
            if a
        ]
        if len(returns) < 2:
            return None

        average = sum(returns) / len(returns)
        variance = (
            sum((value - average) ** 2 for value in returns)
            / (len(returns) - 1)
        )
        return round((variance ** 0.5) * math.sqrt(252) * 100, 3)

    def _range_position(self, closes, period):
        sample = closes[-min(period, len(closes)):]
        if not sample:
            return None
        low = min(sample)
        high = max(sample)
        if high == low:
            return 50.0
        return round((closes[-1] - low) / (high - low) * 100, 2)

    def _distance_from_high(self, closes, period):
        if len(closes) < period:
            return None
        high = max(closes[-period:])
        if not high:
            return None
        return round((closes[-1] / high - 1) * 100, 3)

    def _pct_above_ema(self, closes, ema_period, sample_period):
        if len(closes) < ema_period + sample_period:
            return None

        results = []
        start = len(closes) - sample_period
        for index in range(start, len(closes)):
            ema = self._ema(closes[:index + 1], ema_period)
            if ema is not None:
                results.append(1 if closes[index] > ema else 0)

        if not results:
            return None
        return round(sum(results) / len(results) * 100, 2)

    def _above(self, left, right):
        if left is None or right is None:
            return None
        return left > right


market_metrics = MarketMetrics()
