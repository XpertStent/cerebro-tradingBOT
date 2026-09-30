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


class OrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float = Field(gt=0)
    order_type: str = "MARKET"
    price: float | None = None


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


def build_preview(order: OrderRequest):
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

    if order_type == "LIMIT" and order.price is None:
        raise HTTPException(
            status_code=400,
            detail="LIMIT order requires price"
        )

    quote = opend.get_snapshot(order.symbol)

    estimated_price = (
        float(order.price)
        if order_type == "LIMIT"
        else float(quote["price"])
    )

    result = risk.evaluate_order(
        trading_enabled=config["trading"]["enabled"],
        mode=config["trading"]["mode"],
        symbol=quote["symbol"],
        side=side,
        quantity=order.quantity,
        estimated_price=estimated_price
    )

    result["order_type"] = order_type
    result["requested_price"] = order.price

    return result


@router.post("/preview")
def preview_order(order: OrderRequest):
    try:
        return build_preview(order)

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )


@router.post("/execute")
def execute_order(order: OrderRequest):
    try:
        if config["trading"]["mode"].lower() != "paper":
            raise HTTPException(
                status_code=403,
                detail="Live trading is not supported by this endpoint"
            )

        preview = build_preview(order)

        if not preview["approved"]:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Order blocked by risk engine",
                    "preview": preview
                }
            )

        result = trading.place_paper_order(
            symbol=preview["symbol"],
            side=preview["side"],
            quantity=preview["quantity"],
            order_type=preview["order_type"],
            price=order.price
        )

        return {
            "executed": True,
            "mode": "PAPER",
            "preview": preview,
            "order": result
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
