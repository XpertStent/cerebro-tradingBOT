"""Versioned, isolated corrections for ta_patterns 1.2.1.

Upstream functions are rebound to private namespaces, never patched globally.
Confirmation indices gate availability; actual swing indices define geometry.
Only the audited classical families are exposed, not the 194-name scanner.
"""
from importlib.metadata import version
from types import FunctionType

import numpy as np
import talib
from ta_patterns.chart_patterns import _core, classic, double_multi

VERSION = "cerebro-patterns-1"
LIBRARIES = {"TA-Lib": "0.8.1", "ta-patterns": "1.2.1"}
FAMILIES = {
    "doubles": ("double_top", "double_bottom"),
    "head_shoulders": ("hs_top", "hs_bottom"),
    "triangles": ("ascending_triangle", "descending_triangle", "symmetrical_triangle"),
    "wedges": ("rising_wedge", "falling_wedge"),
    "flags": ("flag_bull", "flag_bear"),
    "pennants": ("pennant_bull", "pennant_bear"),
    "rectangles": ("rectangle_top", "rectangle_bottom"),
}


def verify_libraries():
    for name, expected in LIBRARIES.items():
        if version(name) != expected:
            raise RuntimeError(f"Pattern adapter requires {name} {expected}; run the audited requirements.")


def pivots(values, n=3, pct=None, high=True):
    """Confirmed pivots with full warm-up and filtering at the actual swing."""
    values = np.asarray(values, dtype=float)
    detector = _core.pivot_highs if high else _core.pivot_lows
    result = detector(values, n=n, pct=None)
    result[:2 * n] = False
    if pct is not None:
        filtered = np.zeros(len(result), dtype=bool)
        last = None
        for t in np.flatnonzero(result):
            price = values[t - n]
            if last is None or abs(price - last) / max(abs(last), 1e-10) >= pct:
                filtered[t] = True
                last = price
        result = filtered
    return result


def _namespace(module, overrides):
    private = dict(vars(module))
    for name, function in vars(module).items():
        if isinstance(function, FunctionType) and function.__module__ == module.__name__:
            clone = FunctionType(function.__code__, private, name, function.__defaults__, function.__closure__)
            clone.__kwdefaults__ = function.__kwdefaults__
            private[name] = clone
    private.update(overrides)
    return private


class ChartDetectors:
    def __init__(self, pivot_n):
        self.n = pivot_n
        def highs(a, n=pivot_n, pct=None):
            return pivots(a, n, pct, True)
        def lows(a, n=pivot_n, pct=None):
            return pivots(a, n, pct, False)
        def trendlines(th, ph, tl, pl, count, window, min_pivots=2):
            sh, ih, sl, il, ok = classic._sliding_trendlines(th, ph, tl, pl, count, window, min_pivots)
            # Translating x from confirmation to actual swing shifts intercept.
            return sh, ih + sh * pivot_n, sl, il + sl * pivot_n, ok
        def fit_line(x, y):
            return _core.fit_line_r2(np.asarray(x) - pivot_n, y)
        def flagpole(c, i, min_move, pole_bars):
            if i <= pole_bars:
                return -1, 0
            end, start = i - 1, i - 1 - pole_bars
            move = (c[end] - c[start]) / max(abs(c[start]), 1e-10)
            return (start, 1) if move >= min_move else (start, -1) if move <= -min_move else (-1, 0)
        common = {"pivot_highs": highs, "pivot_lows": lows,
                  "get_pivot_highs": highs, "get_pivot_lows": lows}
        self.classic = _namespace(classic, {**common, "_sliding_trendlines": trendlines,
                                           "fit_line": fit_line, "_flagpole": flagpole})
        self.doubles = _namespace(double_multi, common)

    def scan(self, arrays, configuration):
        # Dimensionless units for slope thresholds; factor is causal and fixed
        # at the first candle, so appending candles cannot change past inputs.
        factor = 100.0 / arrays[3][0]
        scaled = tuple(a * factor for a in arrays[:4])
        output = {}
        for family, names in FAMILIES.items():
            if not configuration.get(family, True):
                continue
            for name in names:
                namespace = self.doubles if family == "doubles" else self.classic
                window = configuration["window"]
                if family in {"flags", "pennants"}:
                    window = min(window, 30 if family == "flags" else 15)
                kwargs = {"mode": "forming", "window": window, "pivot_n": self.n,
                          "pivot_pct": configuration["swing_pct"] / 100 or None}
                if family == "doubles":
                    kwargs.update(tol=configuration["symmetry_pct"] / 100, min_separation=configuration["separation"])
                elif family == "head_shoulders":
                    kwargs.update(shoulder_tol=configuration["symmetry_pct"] / 100, min_separation=configuration["separation"])
                elif name in {"ascending_triangle", "descending_triangle", "rectangle_top", "rectangle_bottom"}:
                    kwargs["flat_tol"] = configuration["flat_slope"]
                elif family in {"flags", "pennants"}:
                    kwargs["min_pole"] = configuration["min_pole_pct"] / 100
                output[name] = namespace[name](*scaled, **kwargs)
        return output


def candle_evidence(arrays, dates, lookback=10):
    evidence = []
    # A positive TA-Lib integer is a detector output, not a calibrated probability.
    neutral = {"CDLDOJI", "CDLLONGLEGGEDDOJI", "CDLRICKSHAWMAN", "CDLHIGHWAVE", "CDLSPINNINGTOP"}
    for name in sorted(n for n in talib.get_functions() if n.startswith("CDL")):
        result = getattr(talib, name)(*arrays[:4])
        for i in np.flatnonzero(result[max(0, len(dates) - lookback):]) + max(0, len(dates) - lookback):
            raw = int(result[i])
            evidence.append({"name": name, "date": dates[i], "value": raw,
                             "direction": "neutral" if name in neutral else "bullish" if raw > 0 else "bearish",
                             "interpretation": "Candle geometry evidence; requires trend and chart context."})
    return sorted(evidence, key=lambda x: (x["date"], x["name"]), reverse=True)
