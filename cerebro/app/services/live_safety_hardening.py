import json
from datetime import datetime, timedelta, timezone
from types import MethodType
from zoneinfo import ZoneInfo

from app.services.activity import activity
from app.services.settings import settings


MAX_LIVE_QUOTE_AGE_SECONDS = 15
NY = ZoneInfo("America/New_York")


def install_live_safety_hardening(live_safety):
    if getattr(live_safety, "_hardening_installed", False):
        return live_safety

    def quote_freshness_check(self, *, mode, snapshot):
        if str(mode or "").upper() != "LIVE":
            return {
                "name": "live_quote_freshness",
                "passed": True,
                "message": "LIVE quote freshness guard is not required in PAPER mode",
            }
        raw = (snapshot or {}).get("updated_at") or (snapshot or {}).get("update_time")
        if not raw:
            return {
                "name": "live_quote_freshness",
                "passed": False,
                "message": "LIVE execution blocked because quote update time is unavailable",
            }
        try:
            text = str(raw).strip()
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt).replace(tzinfo=NY)
                    break
                except ValueError:
                    pass
            if parsed is None:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=NY)
            age = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
        except Exception as exc:
            return {
                "name": "live_quote_freshness",
                "passed": False,
                "message": f"LIVE execution blocked because quote age could not be verified: {exc}",
            }
        passed = age <= MAX_LIVE_QUOTE_AGE_SECONDS
        return {
            "name": "live_quote_freshness",
            "passed": passed,
            "message": (
                f"Quote age {age:.1f}s is within {MAX_LIVE_QUOTE_AGE_SECONDS}s LIVE limit"
                if passed
                else f"Quote is stale ({age:.1f}s old); LIVE limit is {MAX_LIVE_QUOTE_AGE_SECONDS}s"
            ),
            "quote_age_seconds": age,
        }

    def cooldown_check(self, *, mode, symbol, side):
        minutes = int(settings.get("execution.cooldown_minutes") or 0)
        if str(mode or "").upper() != "LIVE" or str(side or "").upper() != "BUY" or minutes <= 0:
            return {
                "name": "live_symbol_cooldown",
                "passed": True,
                "message": "LIVE BUY cooldown is not applicable",
            }

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        latest = None
        for event in activity.list(limit=500, search=str(symbol or "")):
            if event.get("action") not in {"ORDER_SUBMITTED", "AI_ORDER_EXECUTED"}:
                continue
            if str(event.get("symbol") or "").upper() != str(symbol or "").upper():
                continue
            details = event.get("details") or {}
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            if str(details.get("environment") or "").upper() != "LIVE":
                continue
            if str(details.get("side") or details.get("order_side") or "").upper() not in {"BUY", "ADD"}:
                continue
            try:
                stamp = datetime.fromisoformat(str(event.get("timestamp")).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if stamp >= cutoff and (latest is None or stamp > latest):
                latest = stamp

        if latest is None:
            return {
                "name": "live_symbol_cooldown",
                "passed": True,
                "message": f"No LIVE BUY for {symbol} within the {minutes}-minute cooldown",
            }
        remaining = max(
            0,
            int((latest + timedelta(minutes=minutes) - datetime.now(timezone.utc)).total_seconds() // 60) + 1,
        )
        return {
            "name": "live_symbol_cooldown",
            "passed": False,
            "message": f"LIVE BUY cooldown active for {symbol}; wait about {remaining} minute(s)",
        }

    live_safety.quote_freshness_check = MethodType(quote_freshness_check, live_safety)
    live_safety.cooldown_check = MethodType(cooldown_check, live_safety)
    live_safety._hardening_installed = True
    return live_safety
