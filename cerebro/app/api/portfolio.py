from fastapi import APIRouter, HTTPException, Query

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
def portfolio(
    refresh: bool = Query(
        False,
        description="Bypass Cerebro cache"
    )
):
    try:
        return {
            "account": trading.get_account_summary(
                refresh=refresh
            ),

            "positions": trading.get_positions(
                refresh=refresh
            )
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.get("/positions")
def positions(
    refresh: bool = Query(False)
):
    try:
        data = trading.get_positions(
            refresh=refresh
        )

        return {
            "count": len(data),
            "positions": data
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
