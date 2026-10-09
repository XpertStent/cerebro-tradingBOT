import json
from datetime import datetime, timedelta, timezone

from moomoo import OpenQuoteContext, RET_OK

from app.config import config
from app.services.activity import activity
from app.services.settings import settings


REGULAR_US_STATES = {"AFTERNOON"}
EXECUTION_ACTIVITY_ACTIONS = {"ORDER_SUBMITTED", "AI_ORDER_EXECUTED"}


class LiveExecutionSafety:
    """Additional execution guards that only become restrictive in LIVE mode.

    The stable PAPER behaviour remains unchanged. LIVE starts conservatively with
    regular-session-only US equity execution and persistent symbol cooldowns.
    """

    def _quote_context(self):
        return OpenQuoteContext(
            host=config["moomoo"]["host"],
            port=config["moomoo"]["port"],
        )

    @staticmethod
    def _state_text(value):
        return str(value).split(".")[-1].upper()

    @staticmethod
    def _detail_object(value):
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except Exception:
            return {}

    def market_state(self, symbol: str):
        code = str(symbol or "").strip().upper()
        if "." not in code:
            code = f"US.{code}"
        ctx = self._quote_context()
        try:
            ret, data = ctx.get_market_state([code])
            if ret != RET_OK:
                raise RuntimeError(str(data))
            if data.empty:
                raise RuntimeError(f"No market-state data returned for {code}")
            row = data.iloc[0]
            return {
                "symbol": code,
                "state": self._state_text(row.get("market_state")),
                "name": row.get("stock_name"),
            }
        finally:
            ctx.close()

    def market_hours_check(self, *, mode: str, symbol: str):
        if str(mode or "").upper() != "LIVE":
            return {
                "name": "live_regular_session",
                "passed": True,
                "message": "Regular-session LIVE guard is not required in PAPER mode",
            }
        try:
            state = self.market_state(symbol)
        except Exception as exc:
            return {
                "name": "live_regular_session",
                "passed": False,
                "message": f"Unable to verify LIVE market session: {exc}",
            }
        passed = state["state"] in REGULAR_US_STATES
        return {
            "name": "live_regular_session",
            "passed": passed,
            "message": (
                f"US regular session is open ({state['state']})"
                if passed
                else f"LIVE execution is restricted to US regular hours; current state is {state['state']}"
            ),
            "market_state": state["state"],
        }

    def cooldown_check(self, *, mode: str, symbol: str, side: str):
        minutes = int(settings.get("execution.cooldown_minutes") or 0)
        if str(mode or "").upper() != "LIVE" or str(side or "").upper() != "BUY" or minutes <= 0:
            return {
                "name": "live_symbol_cooldown",
                "passed": True,
                "message": "LIVE BUY cooldown is not applicable",
            }

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        recent = activity.list(limit=500, search=str(symbol or ""))
        latest = None
        for event in recent:
            if event.get("action") not in EXECUTION_ACTIVITY_ACTIONS:
                continue
            if str(event.get("symbol") or "").upper() != str(symbol or "").upper():
                continue
            details = self._detail_object(event.get("details"))
            if str(details.get("environment") or "").upper() != "LIVE":
                continue
            try:
                timestamp = datetime.fromisoformat(str(event.get("timestamp")).replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if timestamp >= cutoff and (latest is None or timestamp > latest):
                latest = timestamp

        if latest is None:
            return {
                "name": "live_symbol_cooldown",
                "passed": True,
                "message": f"No LIVE BUY for {symbol} within the {minutes}-minute cooldown",
            }

        remaining = max(0, int((latest + timedelta(minutes=minutes) - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
        return {
            "name": "live_symbol_cooldown",
            "passed": False,
            "message": f"LIVE BUY cooldown active for {symbol}; wait about {remaining} minute(s)",
        }

    def slippage_check(self, *, mode: str, reference_price, current_price):
        maximum = float(settings.get("execution.max_slippage_pct") or 0)
        if str(mode or "").upper() != "LIVE" or maximum <= 0 or reference_price in (None, 0):
            return {
                "name": "live_max_slippage",
                "passed": True,
                "message": "LIVE slippage guard is not applicable",
            }
        try:
            reference = float(reference_price)
            current = float(current_price)
        except (TypeError, ValueError):
            return {
                "name": "live_max_slippage",
                "passed": False,
                "message": "Unable to verify LIVE slippage because the reference/current price is invalid",
            }
        if reference <= 0 or current <= 0:
            return {
                "name": "live_max_slippage",
                "passed": False,
                "message": "Unable to verify LIVE slippage because the reference/current price is unavailable",
            }
        move = abs(current - reference) / reference * 100.0
        passed = move <= maximum + 1e-9
        return {
            "name": "live_max_slippage",
            "passed": passed,
            "message": (
                f"Price drift {move:.3f}% is within the {maximum:.3f}% LIVE slippage limit"
                if passed
                else f"Price drift {move:.3f}% exceeds the {maximum:.3f}% LIVE slippage limit"
            ),
            "slippage_pct": move,
        }

    @staticmethod
    def apply_checks(risk_result: dict, checks: list[dict]):
        result = dict(risk_result)
        merged = list(result.get("risk_checks") or []) + list(checks or [])
        result["risk_checks"] = merged
        result["approved"] = bool(result.get("approved")) and all(bool(check.get("passed")) for check in checks or [])
        return result


live_safety = LiveExecutionSafety()
