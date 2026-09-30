from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import config
from app.services.trading import trading
from app.services.opend import opend
from app.services.risk import risk


router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)


class OrderPreviewRequest(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    order_type: str = "MARKET"


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


@router.post("/preview")
def preview_order(order: OrderPreviewRequest):
    try:
        side = order.side.upper()
        order_type = order.order_type.upper()

        if side not in ("BUY", "SELL"):
            raise HTTPException(
                status_code=400,
                detail="side must be BUY or SELL"
            )

        if order_type not in ("MARKET", "LIMIT"):
            raise HTTPException(
                status_code=400,
                detail="order_type must be MARKET or LIMIT"
            )

        quote = opend.get_snapshot(order.symbol)

        result = risk.evaluate_order(
            trading_enabled=config["trading"]["enabled"],
            mode=config["trading"]["mode"],
            symbol=quote["symbol"],
            side=side,
            quantity=order.quantity,
            estimated_price=float(quote["price"])
        )

        result["order_type"] = order_type

        return result

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
