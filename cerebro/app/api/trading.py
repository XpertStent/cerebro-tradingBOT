import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.activity import activity
from app.services.live_credentials import configured_unlock_hash
from app.services.trading import trading


router = APIRouter(prefix="/trading", tags=["Trading"])
_MD5_RE = re.compile(r"^[0-9a-f]{32}$")


class UnlockRequest(BaseModel):
    password_md5: str | None = None


class SelectAccountRequest(BaseModel):
    account_id: str


def _status(refresh=False):
    status = trading.trading_status(refresh=refresh)
    status["unlock_hash_configured"] = bool(configured_unlock_hash())
    status["interactive_unlock_supported"] = True
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
            "interactive_unlock_supported": status.get("interactive_unlock_supported"),
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
    try:
        supplied_hash = (payload.password_md5 if payload else None)
        password_md5 = str(supplied_hash or configured_unlock_hash() or "").strip().lower()

        if not password_md5:
            raise ValueError(
                "Enter your Moomoo trading password in the unlock dialog, or configure MOOMOO_TRADING_PASSWORD_MD5 on the Cerebro container."
            )
        if not _MD5_RE.fullmatch(password_md5):
            raise ValueError("Trading password hash must be a 32-character lowercase MD5 value")

        result = trading.unlock_trade(password_md5=password_md5)
        return {
            **result,
            "status": _status(refresh=True),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        activity.write(
            category="SECURITY",
            action="LIVE_TRADING_UNLOCK_FAILED",
            message="Live trading unlock failed",
            level="ERROR",
            # Never log the supplied password hash. It is a reusable credential.
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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
