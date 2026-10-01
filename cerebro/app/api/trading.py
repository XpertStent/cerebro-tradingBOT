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


@router.get("/status")
def trading_status():
    return trading.trading_status(refresh=False)


@router.get("/accounts")
def trading_accounts():
    try:
        status = trading.trading_status(refresh=True)
        return {
            "mode": status.get("mode"),
            "selected_account": status.get("account"),
            "accounts": status.get("available_live_accounts") or [],
            "unlocked": status.get("unlocked"),
            "ready": status.get("ready"),
            "unlock_hash_configured": bool(configured_unlock_hash()),
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
            "status": trading.trading_status(refresh=True),
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/unlock")
def unlock_trade(payload: UnlockRequest | None = None):
    try:
        password_md5 = (payload.password_md5 if payload else None) or configured_unlock_hash()
        if not password_md5:
            raise ValueError(
                "No server-side live unlock hash is configured. Set MOOMOO_TRADING_PASSWORD_MD5 on the Cerebro container and redeploy."
            )
        result = trading.unlock_trade(password_md5=password_md5)
        return {
            **result,
            "status": trading.trading_status(refresh=True),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        activity.write(
            category="SECURITY",
            action="LIVE_TRADING_UNLOCK_FAILED",
            message="Live trading unlock failed",
            level="ERROR",
            details={"error": str(exc)},
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/lock")
def lock_trade():
    try:
        result = trading.lock_trade()
        return {
            **result,
            "status": trading.trading_status(refresh=False),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
