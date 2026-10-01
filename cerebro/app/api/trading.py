import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.activity import activity
from app.services.live_credentials import configured_unlock_hash
from app.services.trading import trading


router = APIRouter(prefix="/trading", tags=["Trading"])


class UnlockRequest(BaseModel):
    password_md5: str | None = None


class SelectAccountRequest(BaseModel):
    account_id: str


def _status(refresh=False):
    status = trading.trading_status(refresh=refresh)
    status["unlock_hash_configured"] = bool(configured_unlock_hash())
    return status


@router.get("/status")
def trading_status():
    return _status(refresh=False)


@router.get("/accounts")
def trading_accounts():
    try:
        status = _status(refresh=True)
        return {
            "mode": status.get("mode"),
            "selected_account": status.get("account"),
            "accounts": status.get("available_live_accounts") or [],
            "unlocked": status.get("unlocked"),
            "ready": status.get("ready"),
            "unlock_hash_configured": status.get("unlock_hash_configured"),
            "error": status.get("error"),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/account")
def select_account(payload: SelectAccountRequest):
    try:
        account = trading.select_live_account(payload.account_id)
        return {
            "selected": True,
            "account": account,
            "status": _status(refresh=True),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/unlock")
def unlock_trade(payload: UnlockRequest | None = None):
    password_md5 = None
    try:
        password_md5 = (payload.password_md5 if payload else None) or configured_unlock_hash()
        if password_md5:
            password_md5 = password_md5.strip().lower()
        if not password_md5:
            raise ValueError(
                "Enter your trading password or configure MOOMOO_TRADING_PASSWORD_MD5."
            )
        if not re.fullmatch(r"[0-9a-f]{32}", password_md5):
            raise ValueError("Invalid trading credential.")
        result = trading.unlock_trade(password_md5=password_md5)
        return {
            **result,
            "status": _status(refresh=True),
        }
    except ValueError as exc:
        detail = (
            "Invalid trading credential." if password_md5
            else "Enter your trading password or configure MOOMOO_TRADING_PASSWORD_MD5."
        )
        raise HTTPException(status_code=400, detail=detail) from None
    except Exception as exc:
        activity.write(
            category="SECURITY",
            action="LIVE_TRADING_UNLOCK_FAILED",
            message="Live trading unlock failed",
            level="ERROR",
            details={"error": "Broker unlock failed"},
        )
        raise HTTPException(
            status_code=403,
            detail="Unable to unlock trading. Check your trading password and OpenD connection.",
        ) from None


@router.post("/lock")
def lock_trade():
    try:
        result = trading.lock_trade()
        return {
            **result,
            "status": _status(refresh=False),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
