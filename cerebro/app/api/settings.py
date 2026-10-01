from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.settings import settings
from app.services.trading import trading


router = APIRouter(prefix="/settings", tags=["Settings"])


class SettingsUpdate(BaseModel):
    values: dict


class SettingsReset(BaseModel):
    section: str | None = None


ACTIVE_PHASE_KEYS = {
    "ai.decision.model",
    "ai.decision.reasoning_effort",
    "risk.max_daily_loss",
    "risk.max_position_pct",
    "risk.max_invested_pct",
    "risk.min_cash_reserve_pct",
    "risk.max_new_positions_per_run",
    "risk.max_order_adv_pct",
    "execution.auto_execute",
    "execution.require_preview",
    "execution.default_order_type",
    "execution.max_slippage_pct",
    "execution.cooldown_minutes",
}


def _public_snapshot():
    snapshot = settings.public_snapshot()
    for item in snapshot.get("settings") or []:
        key = item.get("key")
        if key in ACTIVE_PHASE_KEYS:
            item["future"] = False

        if key == "trading.mode":
            item["options"] = ["paper", "live"]
            item["description"] = (
                "Broker execution environment. PAPER uses the simulated account; LIVE uses the explicitly selected ACTIVE real Moomoo US-enabled account and requires trade unlock."
            )

        if key == "trading.enabled":
            item["description"] = (
                "Master kill switch for new broker orders. Turning this off blocks both PAPER and LIVE execution."
            )

        if key == "execution.auto_execute":
            item["label"] = "Authorize AI Auto-Execution"
            item["description"] = (
                "When enabled, risk-approved AI broker actions execute without manual proposal approval. In LIVE mode this can submit real-money orders only while trading is deliberately unlocked; if locked, Cerebro falls back to manual approval."
            )

        if key == "execution.require_preview":
            item["description"] = (
                "Every manual execution performs a fresh server-side preview/risk pass even when called directly through the API. The UI also shows that preview before submission."
            )

        if key == "execution.max_slippage_pct":
            item["description"] = (
                "Maximum price drift allowed between an AI proposal's reference price and its fresh pre-submit price in LIVE mode."
            )

        if key == "execution.cooldown_minutes":
            item["description"] = (
                "LIVE BUY cooldown per symbol after a recent Cerebro live execution. SELL/REDUCE exits are not blocked by this cooldown."
            )

        if key == "risk.max_order_value":
            item["description"] = (
                "Absolute order-value ceiling. For BUY orders Cerebro also scales the effective limit down to the current account size using the single-position percentage cap, so smaller LIVE accounts do not inherit paper-account sizing."
            )

        if key == "risk.max_daily_loss":
            item["description"] = (
                "LIVE guard uses USD account equity change since the first observation of the US trading day, including market moves and cash transfers. This is not realized P&L."
            )

        if key == "ai.decision.model":
            item["description"] = "Model used for final portfolio decisions. Separate from the research/news model."

    return snapshot


@router.get("")
def get_settings():
    return _public_snapshot()


@router.put("")
def update_settings(payload: SettingsUpdate):
    try:
        old_mode = str(settings.get("trading.mode") or "paper").lower()
        requested_mode = payload.values.get("trading.mode")
        if requested_mode is not None and str(requested_mode).lower() not in {"paper", "live"}:
            raise ValueError("trading.mode must be paper or live")

        settings.update_many(payload.values)
        new_mode = str(settings.get("trading.mode") or "paper").lower()
        if new_mode != old_mode:
            trading.mode_changed()

        return _public_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset")
def reset_settings(payload: SettingsReset):
    try:
        old_mode = str(settings.get("trading.mode") or "paper").lower()
        settings.reset(payload.section)
        new_mode = str(settings.get("trading.mode") or "paper").lower()
        if new_mode != old_mode:
            trading.mode_changed()
        return _public_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
