from fastapi import APIRouter, HTTPException

from app.services.opend import opend


router = APIRouter(
    prefix="/markets",
    tags=["Markets"]
)


@router.get("/status")
def market_status():
    try:
        markets = opend.get_market_states()

        return {
            "count": len(markets),
            "markets": markets
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
