from fastapi import APIRouter, HTTPException

from app.services.trading import trading


router = APIRouter(
    prefix="/portfolio",
    tags=["Portfolio"]
)


@router.get("/accounts")
def accounts():
    try:
        return {
            "accounts": trading.get_accounts()
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.get("/")
def portfolio():
    try:
        return {
            "account": trading.get_account_summary(),
            "positions": trading.get_positions()
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.get("/positions")
def positions():
    try:
        positions = trading.get_positions()

        return {
            "count": len(positions),
            "positions": positions
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
