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


@router.get("")
def get_settings():
    return settings.public_snapshot()


@router.put("")
def update_settings(payload: SettingsUpdate):
    try:
        return settings.update_many(payload.values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@router.post("/reset")
def reset_settings(payload: SettingsReset):
    try:
        return settings.reset(payload.section)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
