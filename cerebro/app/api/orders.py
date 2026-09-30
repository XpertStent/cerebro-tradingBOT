from fastapi import APIRouter, HTTPException
from app.services.trading import trading

router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)


@router.get("/")
def orders():
    try:
        data = trading.get_orders()

        return {
            "count": len(data),
            "orders": data
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
