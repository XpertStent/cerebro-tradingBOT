from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.settings import settings


router = APIRouter(
    prefix="/settings",
    tags=["Settings"],
)


class SettingsUpdate(BaseModel):
    values: dict


class SettingsReset(BaseModel):
    section: str | None = None


# Live trading is intentionally postponed. Correct any old persisted UI-only
# value so the system status and broker implementation cannot disagree.
if str(settings.get("trading.mode") or "paper").lower() != "paper":
    settings.update_many({"trading.mode": "paper"})


ACTIVE_PHASE_KEYS = {
    "ai.decision.model",
    "ai.decision.reasoning_effort",
    "risk.max_position_pct",
    "risk.max_invested_pct",
    "risk.min_cash_reserve_pct",
    "risk.max_new_positions_per_run",
    "risk.max_order_adv_pct",
    "execution.auto_execute",
    "execution.default_order_type",
}


def _public_snapshot():
    snapshot = settings.public_snapshot()
    for item in snapshot.get("settings") or []:
        key = item.get("key")
        if key in ACTIVE_PHASE_KEYS:
            item["future"] = False

        if key == "trading.mode":
            item["options"] = ["paper"]
            item["value"] = "paper"
            item["description"] = (
                "Paper trading only. Live broker execution will be implemented "
                "and separately validated in a later phase."
            )

        if key == "execution.auto_execute":
            item["label"] = "Authorize AI Auto-Execution"
            item["description"] = (
                "OFF by default. When enabled, risk-approved AI paper orders "
                "execute immediately after the model decision without manual "
                "Approve / Reject controls."
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
        requested_mode = payload.values.get("trading.mode")
        if requested_mode is not None and str(requested_mode).lower() != "paper":
            raise ValueError("Live trading is not implemented yet; trading.mode must remain paper")
        settings.update_many(payload.values)
        return _public_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset")
def reset_settings(payload: SettingsReset):
    try:
        settings.reset(payload.section)
        # A reset must still retain the paper-only safety boundary.
        if str(settings.get("trading.mode") or "paper").lower() != "paper":
            settings.update_many({"trading.mode": "paper"})
        return _public_snapshot()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
