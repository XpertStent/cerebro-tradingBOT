"""Explainable completed-daily-bar pattern lifecycle. No broker operations."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import talib
from ta_patterns.chart_patterns._core import fit_line_r2

from app.services.pattern_detectors import ChartDetectors, FAMILIES, LIBRARIES, VERSION, candle_evidence, pivots, verify_libraries

DEFAULTS = {"mode": "observe", "pivot_n": 3, "window": 120, "swing_pct": 0.0,
            "symmetry_pct": 5.0, "separation": 6, "flat_slope": 0.02,
            "min_pole_pct": 5.0, "breakout_atr": 0.1, "volume_ratio": 0.0,
            "expiry_bars": 30, "candle_lookback": 10, "candles": True,
            **{family: True for family in FAMILIES}}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def clean_bars(rows):
    dates, columns = [], [[] for _ in range(5)]
    for row in rows:
        raw = str(row.get("trade_date") or row.get("date") or row.get("time") or "")
        date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 and raw.isdigit() else raw[:10]
        from datetime import date as calendar_date
        calendar_date.fromisoformat(date)
        if dates and date <= dates[-1]:
            raise ValueError("Pattern history must have unique ascending daily dates.")
        values = [float(row[key]) for key in ("open", "high", "low", "close", "volume")]
        o, h, l, c, v = values
        if not all(np.isfinite(values)) or min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or h < l:
            raise ValueError("Pattern history contains invalid OHLCV candles.")
        dates.append(date)
        for column, value in zip(columns, values):
            column.append(value)
    return dates, tuple(np.asarray(c, dtype=np.float64) for c in columns)


def _line(points):
    x = np.array([p["index"] for p in points], dtype=float)
    y = np.array([p["price"] for p in points], dtype=float)
    slope, intercept, r2 = fit_line_r2(x, y)
    return [float(slope), float(intercept)], float(r2)


def _value(line, i):
    return line[0] * i + line[1]


def _pivots(arrays, dates, cfg):
    output = {}
    for kind, source in (("high", arrays[1]), ("low", arrays[2])):
        times = np.flatnonzero(pivots(source, cfg["pivot_n"], cfg["swing_pct"] / 100 or None, kind == "high"))
        points = []
        for t in times:
            index = int(t) - cfg["pivot_n"]
            point = {"index": index, "confirmation_index": int(t), "date": dates[index],
                     "confirmation_date": dates[t], "price": float(source[index]), "kind": kind}
            # Equal neighbouring pivots belong to one swing, not two votes.
            if points and int(t) - points[-1]["confirmation_index"] <= cfg["pivot_n"]:
                continue
            points.append(point)
        output[kind] = points
    return output


def geometry(name, t, all_points, arrays, cfg):
    """Reconstruct only the pivot evidence available at t; reject weak shapes."""
    n, window = cfg["pivot_n"], cfg["window"]
    if name.startswith("flag_"):
        window = min(window, 30)
    elif name.startswith("pennant_"):
        window = min(window, 15)
    highs = [p for p in all_points["high"] if t - window <= p["confirmation_index"] <= t]
    lows = [p for p in all_points["low"] if t - window <= p["confirmation_index"] <= t]
    top = name in {"double_top", "hs_top", "descending_triangle", "rising_wedge", "flag_bear", "pennant_bear", "rectangle_top"}
    direction = "neutral" if name == "symmetrical_triangle" else "bearish" if top else "bullish"
    if name.startswith("double_"):
        main = [p for p in (highs if top else lows) if p["confirmation_index"] < t]
        opposite = lows if top else highs
        if len(main) < 2:
            return None
        a, b = main[-2:]
        between = [p for p in opposite if a["confirmation_index"] < p["confirmation_index"] < b["confirmation_index"]]
        if not between or b["index"] - a["index"] < cfg["separation"]:
            return None
        symmetry = abs(a["price"] - b["price"]) / max(a["price"], b["price"])
        if symmetry > cfg["symmetry_pct"] / 100:
            return None
        neck = between[-1]
        upper = [0.0, max(a["price"], b["price"])] if top else [0.0, neck["price"]]
        lower = [0.0, neck["price"]] if top else [0.0, min(a["price"], b["price"])]
        points = [a, neck, b]
        checks = {"symmetry_pct": round(symmetry * 100, 3), "separation_bars": b["index"] - a["index"]}
    elif name.startswith("hs_"):
        main, opposite = (highs, lows) if top else (lows, highs)
        rs = next((p for p in main if p["confirmation_index"] == t), None)
        left = [p for p in main if p["confirmation_index"] < t]
        if rs is None or len(left) < 2:
            return None
        head = (max if top else min)(left, key=lambda p: p["price"])
        shoulders = [p for p in left if p["index"] <= head["index"] - cfg["separation"]]
        if not shoulders or rs["index"] - head["index"] < cfg["separation"]:
            return None
        ls = shoulders[-1]
        head_is_extreme = head["price"] > max(ls["price"], rs["price"]) if top else head["price"] < min(ls["price"], rs["price"])
        if not head_is_extreme:
            return None
        v1 = [p for p in opposite if ls["index"] < p["index"] < head["index"]]
        v2 = [p for p in opposite if head["index"] < p["index"] < rs["index"]]
        if not v1 or not v2:
            return None
        symmetry = abs(ls["price"] - rs["price"]) / max(ls["price"], rs["price"])
        if symmetry > cfg["symmetry_pct"] / 100:
            return None
        neck, _ = _line([v1[-1], v2[-1]])
        upper = [0.0, head["price"]] if top else neck
        lower = neck if top else [0.0, head["price"]]
        points = [ls, v1[-1], head, v2[-1], rs]
        checks = {"shoulder_symmetry_pct": round(symmetry * 100, 3), "head_is_extreme": True}
    else:
        if len(highs) < 2 or len(lows) < 2:
            return None
        upper, hi_r2 = _line(highs)
        lower, lo_r2 = _line(lows)
        if min(hi_r2, lo_r2) < .5 or _value(upper, t) <= _value(lower, t):
            return None
        checks = {"upper_touches": len(highs), "lower_touches": len(lows),
                  "upper_r2": round(hi_r2, 4), "lower_r2": round(lo_r2, 4)}
        if "triangle" in name or "wedge" in name or "pennant" in name:
            if lower[0] <= upper[0]:
                return None
            apex = (upper[1] - lower[1]) / (lower[0] - upper[0])
            if apex <= t or apex - t > 2 * window:
                return None
            checks["bars_to_apex_at_recognition"] = round(apex - t, 2)
        if name.startswith(("flag_", "pennant_")):
            end, start = t - window - 1, t - window - 11
            if start < 0:
                return None
            move = (arrays[3][end] / arrays[3][start] - 1) * 100
            if (move >= 0) != (direction == "bullish") or abs(move) < cfg["min_pole_pct"]:
                return None
            checks["flagpole_move_pct"] = round(move, 3)
            if name.startswith("flag_"):
                ratio = abs(upper[0] - lower[0]) / max(abs(upper[0]), abs(lower[0]), 1e-10)
                if ratio > .25:
                    return None
                checks["parallel_slope_difference"] = round(ratio, 4)
        points = sorted(highs + lows, key=lambda p: p["index"])
    if _value(upper, t) <= _value(lower, t):
        return None
    return {"points": points, "upper": upper, "lower": lower, "direction": direction, "checks": checks}


def chart_events(arrays, dates, cfg):
    signals = ChartDetectors(cfg["pivot_n"]).scan(arrays, cfg)
    all_points = _pivots(arrays, dates, cfg)
    atr = talib.ATR(arrays[1], arrays[2], arrays[3], timeperiod=14)
    active, events = {}, []
    for t, date in enumerate(dates):
        for name, series in signals.items():
            if not series[t]:
                continue
            geo = geometry(name, t, all_points, arrays, cfg)
            if not geo:
                continue
            anchors = [(p["date"], p["kind"]) for p in geo["points"]]
            identifier = fingerprint([name, anchors])[:20]
            if identifier in active:
                continue
            event = {"id": identifier, "pattern": name, "family": next(k for k, v in FAMILIES.items() if name in v),
                     "status": "FORMING", "direction": geo["direction"], "recognition_date": date,
                     "formation_start": geo["points"][0]["date"], "last_swing_date": geo["points"][-1]["date"],
                     "confirmation_date": None, "invalidation_date": None, "expiry_date": None,
                     "pivot_delay_bars": cfg["pivot_n"], "points": geo["points"], "checks": geo["checks"],
                     "_geometry": geo, "_recognized": t, "_atr_buffer": float(atr[t]) * cfg["breakout_atr"] if np.isfinite(atr[t]) else 0,
                     "explanation": "Shape detected by ta_patterns with Cerebro geometry checks. Confirmation requires a subsequent completed daily close beyond the boundary.",
                     "orders_armed": False}
            active[identifier] = event
            events.append(event)
        for event in active.values():
            if event["status"] not in {"FORMING", "CONFIRMED"} or t <= event["_recognized"]:
                continue
            geo = event["_geometry"]
            upper, lower = _value(geo["upper"], t), _value(geo["lower"], t)
            close, buffer = arrays[3][t], event["_atr_buffer"]
            direction = event["direction"]
            if event["status"] == "FORMING":
                if t - event["_recognized"] > cfg["expiry_bars"] or upper <= lower:
                    event.update(status="EXPIRED", expiry_date=date)
                    continue
                up, down = close > upper + buffer, close < lower - buffer
                opposite = (direction == "bullish" and down) or (direction == "bearish" and up)
                if opposite:
                    event.update(status="INVALIDATED", invalidation_date=date)
                    continue
                breakout = (up and direction in {"bullish", "neutral"}) or (down and direction in {"bearish", "neutral"})
                if breakout:
                    baseline = np.mean(arrays[4][max(0, t - 20):t])
                    ratio = float(arrays[4][t] / baseline) if baseline > 0 else None
                    event["breakout_volume_ratio"] = ratio
                    if cfg["volume_ratio"] and (ratio is None or ratio < cfg["volume_ratio"]):
                        continue
                    event.update(status="CONFIRMED", confirmation_date=date,
                                 direction="bullish" if up else "bearish", confirmation_close=float(close))
            elif (direction == "bullish" and close < lower - buffer) or (direction == "bearish" and close > upper + buffer):
                event.update(status="FAILED", invalidation_date=date)
    for event in events:
        geo = event.pop("_geometry")
        start = geo["points"][0]["index"]
        recognized = event.pop("_recognized")
        terminal_date = event["invalidation_date"] or event["expiry_date"]
        last = dates.index(terminal_date) if terminal_date else len(dates) - 1
        event["trigger"] = {"type": "completed_daily_close", "buffer": event.pop("_atr_buffer"),
                            "above": float(_value(geo["upper"], last)), "below": float(_value(geo["lower"], last)),
                            "volume_ratio_required": cfg["volume_ratio"], "broker_order": False}
        event["lines"] = [{"label": label, "slope_per_bar": line[0], "points": [
            {"date": dates[start], "value": float(_value(line, start))},
            {"date": dates[last], "value": float(_value(line, last))},
        ]} for label, line in (("Resistance / upper", geo["upper"]), ("Support / lower", geo["lower"]))]
        event["last_evaluated_date"] = dates[last]
        # Availability and geometry are separate; never backdate a signal to its swing.
        event["recognition_index"] = recognized
    return sorted(events, key=lambda e: (e["recognition_date"], e["id"]), reverse=True)


class PatternEngine:
    def analyze(self, rows, configuration=None):
        verify_libraries()
        cfg = {**DEFAULTS, **(configuration or {})}
        dates, arrays = clean_bars(rows)
        minimum = cfg["window"] + 2 * cfg["pivot_n"] + 2
        if len(dates) < minimum:
            raise ValueError(f"Pattern analysis requires at least {minimum} completed candles.")
        # Both independent analyses share immutable arrays, not broker requests.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="pattern-evidence") as pool:
            charts = pool.submit(chart_events, arrays, dates, cfg)
            candles = pool.submit(candle_evidence, arrays, dates, cfg["candle_lookback"]) if cfg["candles"] else None
            events = charts.result()
            evidence = candles.result() if candles else []
        return {"available": True, "version": VERSION, "libraries": LIBRARIES,
                "timeframe": "1d", "bars_analyzed": len(dates), "oldest_candle_date": dates[0],
                "latest_candle_date": dates[-1], "latest_close": float(arrays[3][-1]), "mode": cfg["mode"], "configuration": cfg,
                "event_count": len(events), "events": events[:200], "candle_evidence": evidence,
                "interpretation": "Deterministic geometry evidence, not success probabilities or executable orders."}


pattern_engine = PatternEngine()
