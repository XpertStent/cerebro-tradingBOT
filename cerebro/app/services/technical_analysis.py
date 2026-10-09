"""Shared history -> versioned pattern cache -> UI or explicitly enabled AI advisory."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.services.pattern_engine import DEFAULTS, pattern_engine, fingerprint
from app.services.pattern_detectors import VERSION


class TechnicalAnalysisService:
    def __init__(self, path="/data/technical_patterns.db", settings_service=None, market_service=None):
        self.path = Path(path)
        self.settings = settings_service
        self.market = market_service
        self._lock = threading.RLock()

    def dependencies(self):
        if self.settings is None:
            from app.services.settings import settings
            self.settings = settings
        if self.market is None:
            from app.services.market_data import market_data
            self.market = market_data
        return self.settings, self.market

    def configuration(self):
        settings, _ = self.dependencies()
        return {key: settings.get(f"patterns.{key}", value) for key, value in DEFAULTS.items()}

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS pattern_results (
                    namespace TEXT, fingerprint TEXT, payload TEXT NOT NULL, created_at TEXT,
                    PRIMARY KEY(namespace,fingerprint)
                );
                CREATE TABLE IF NOT EXISTS pattern_events (
                    namespace TEXT, event_id TEXT, fingerprint TEXT, payload TEXT NOT NULL,
                    first_observed_at TEXT, last_observed_at TEXT,
                    PRIMARY KEY(namespace,event_id)
                );
            """)
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def unavailable(symbol, reason, cfg=None, quality=None):
        return {"symbol": symbol, "available": False, "reason": reason, "version": VERSION,
                "mode": (cfg or {}).get("mode", "observe"), "timeframe": "1d",
                "data_quality": quality or {}, "events": [], "candle_evidence": []}

    def analyze_series(self, symbol, series, configuration=None):
        cfg = configuration
        try:
            cfg = cfg or self.configuration()
            return self._analyze_series(symbol, series, cfg)
        except Exception:
            return self.unavailable(symbol, "PATTERN_ANALYSIS_UNAVAILABLE", cfg)

    def _analyze_series(self, symbol, series, configuration=None):
        cfg = configuration or self.configuration()
        quality = deepcopy(series.get("history_sync") or {})
        if cfg["mode"] == "off":
            return self.unavailable(symbol, "DISABLED", cfg)
        if quality.get("fresh") is not True or quality.get("usable") is not True:
            return self.unavailable(symbol, "CURRENT_COMPLETED_HISTORY_REQUIRED", cfg, quality)
        rows = series.get("bars") or []
        expected = str(quality.get("expected_complete_date") or "").replace("-", "")
        if not expected or any(str(r.get("trade_date") or "").replace("-", "")[:8] > expected for r in rows):
            return self.unavailable(symbol, "INCOMPLETE_CANDLE", cfg, quality)
        if not rows or str(rows[-1].get("trade_date") or "").replace("-", "")[:8] != expected:
            return self.unavailable(symbol, "CURRENT_COMPLETED_HISTORY_REQUIRED", cfg, quality)
        provenance = {key: quality.get(key) for key in ("provider", "feed", "adjustment", "session", "delay_minutes", "adjustment_basis")}
        if not all(provenance.get(k) for k in ("provider", "feed", "adjustment", "session")):
            return self.unavailable(symbol, "HISTORY_PROVENANCE_REQUIRED", cfg, quality)
        for row in rows:
            if any(row.get(k) is not None and row[k] != provenance[k] for k in ("provider", "feed", "adjustment", "session")):
                return self.unavailable(symbol, "MIXED_HISTORY_PROVENANCE", cfg, quality)
        namespace = fingerprint([symbol, "1d", provenance, cfg, VERSION])
        # Adjustment revisions invalidate result caches, but the same dated
        # formation retains its first observation across subsequent sessions.
        event_namespace = fingerprint([symbol, "1d", {k: v for k, v in provenance.items() if k != "adjustment_basis"}, cfg, VERSION])
        content = [{k: r.get(k) for k in ("trade_date", "time", "open", "high", "low", "close", "volume")} for r in rows]
        try:
            content_fingerprint = fingerprint(content)
        except (TypeError, ValueError):
            return self.unavailable(symbol, "INVALID_HISTORY", cfg, quality)
        # Serialize identical in-process work. SQLite keys deduplicate across restarts.
        with self._lock:
            with self.connect() as conn:
                cached = conn.execute("SELECT payload FROM pattern_results WHERE namespace=? AND fingerprint=?", (namespace, content_fingerprint)).fetchone()
            if cached:
                result = json.loads(cached[0])
                result.update(source="ANALYSIS_CACHE", data_quality=quality)
                return result
            try:
                result = pattern_engine.analyze(rows, cfg)
            except (ValueError, KeyError, TypeError):
                return self.unavailable(symbol, "INVALID_OR_INSUFFICIENT_HISTORY", cfg, quality)
            now = datetime.now(timezone.utc).isoformat()
            result.update(symbol=symbol, source="ANALYZED", generated_at=now,
                          candle_fingerprint=content_fingerprint, data_quality=quality, provenance=provenance)
            with self.connect() as conn:
                for event in result["events"]:
                    previous = conn.execute("SELECT first_observed_at FROM pattern_events WHERE namespace=? AND event_id=?", (event_namespace, event["id"])).fetchone()
                    event["first_observed_at"] = previous[0] if previous else now
                    event["last_observed_at"] = now
                    conn.execute("INSERT INTO pattern_events VALUES(?,?,?,?,?,?) ON CONFLICT(namespace,event_id) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,last_observed_at=excluded.last_observed_at",
                                 (event_namespace, event["id"], content_fingerprint, json.dumps(event, allow_nan=False), event["first_observed_at"], now))
                conn.execute("INSERT OR REPLACE INTO pattern_results VALUES(?,?,?,?)", (namespace, content_fingerprint, json.dumps(result, allow_nan=False), now))
                # One current result per exact namespace; events keep their recorded observation times.
                conn.execute("DELETE FROM pattern_results WHERE namespace=? AND fingerprint<>?", (namespace, content_fingerprint))
            return result

    def build(self, symbol):
        cfg = self.configuration()
        if cfg["mode"] == "off":
            return self.unavailable(symbol, "DISABLED", cfg)
        _, market = self.dependencies()
        provider_configuration = market.configuration()
        try:
            history = market.completed_history(symbol, minimum_bars=cfg["window"] + 2 * cfg["pivot_n"] + 2)
            series = {"bars": history["candles"], "history_sync": {k: v for k, v in history.items() if k != "candles"}}
            result = self.analyze_series(symbol, series, cfg)
        except Exception:
            return self.unavailable(symbol, "HISTORY_OR_ANALYSIS_UNAVAILABLE", cfg)
        if cfg != self.configuration() or provider_configuration != market.configuration():
            return self.unavailable(symbol, "SETTINGS_CHANGED_DURING_ANALYSIS", cfg)
        return result

    def is_current(self, result, symbol, configuration=None):
        """Check saved evidence against the current calendar/provider without fetching."""
        if not result or not result.get("available") or result.get("symbol") != symbol:
            return False
        if result.get("version") != VERSION or result.get("configuration") != (configuration or self.configuration()):
            return False
        _, market = self.dependencies()
        quality = dict(result.get("data_quality") or {})
        try:
            quality["last_cached_date"] = int(result["latest_candle_date"].replace("-", ""))
            return market.metrics_current(symbol, {"available": True, "data_quality": quality})
        except (KeyError, TypeError, ValueError):
            return False

    def model_context(self, result):
        if not result or result.get("mode") != "advisory":
            return None
        if not result.get("available"):
            return {k: result[k] for k in ("available", "reason", "version", "mode")}
        events = [e for e in result["events"] if e["status"] in {"FORMING", "CONFIRMED"}]
        # Related variants/overlapping detections do not become independent votes.
        grouped = {}
        for event in sorted(events, key=lambda e: (e["status"] == "CONFIRMED", e["recognition_date"]), reverse=True):
            grouped.setdefault((event["family"], event["direction"]), event)
        compact_events = []
        for event in list(grouped.values())[:6]:
            compact = {k: event[k] for k in ("pattern", "status", "direction", "recognition_date", "last_swing_date", "confirmation_date", "pivot_delay_bars", "trigger", "checks")}
            points = event["points"]
            if len(points) > 6:
                # Keep the first and last swing on each fitted boundary. Full
                # geometry stays in the inspector/cache, not in every prompt.
                edges = []
                for kind in ("high", "low"):
                    selected = [p for p in points if p["kind"] == kind]
                    if selected:
                        edges.extend([selected[0], selected[-1]] if len(selected) > 1 else selected)
                points = sorted(edges, key=lambda p: p["index"])
            compact["points"] = [{k: p[k] for k in ("date", "confirmation_date", "kind", "price")} for p in points]
            compact["geometry_points_total"] = len(event["points"])
            compact_events.append(compact)
        return {"available": True, "mode": "advisory", "version": result["version"],
                "latest_candle_date": result["latest_candle_date"], "bars_analyzed": result["bars_analyzed"],
                "provenance": result["provenance"], "data_quality": result["data_quality"],
                "chart_patterns": compact_events,
                "candle_evidence": result["candle_evidence"][:16],
                "confirmation_policy": {"unconfirmed_expiry_bars": result["configuration"]["expiry_bars"],
                    "invalidation": "A completed close beyond the opposite boundary and buffer invalidates a forming directional pattern or fails a confirmed one. Converging boundaries crossing also expire an unconfirmed formation.",
                    "volume_baseline": "Preceding 20 completed candles from the same provider/feed."},
                "interpretation": "Advisory geometry only. Forming means unconfirmed, neutral means no direction yet. Values are not win probabilities. Pattern levels are adjusted historical prices, not executable order prices. No orders or triggers are armed. Portfolio and risk constraints still apply."}


technical_analysis = TechnicalAnalysisService()
