from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from moomoo import ModifyOrderOp, RET_OK, TrdEnv

from app.services.trading import trading
from app.services.opend import opend
from app.services.risk import risk
from app.services.activity import activity
from app.services.settings import settings


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


TERMINAL_ORDER_STATES = {
    "FILLED_ALL",
    "CANCELLED_ALL",
    "CANCELED_ALL",
    "FAILED",
    "DISABLED",
    "DELETED",
}


@router.get("/")
def orders():
    try:
        data = trading.get_orders()
        return {
            "count": len(data),
            "orders": data
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/{order_id}")
def cancel_pending_order(order_id: str):
    """Cancel a non-terminal PAPER order reported by OpenD."""
    try:
        if str(settings.get("trading.mode")).lower() != "paper":
            raise HTTPException(
                status_code=403,
                detail="Live-order cancellation is not implemented",
            )

        existing = next(
            (
                item for item in trading.get_orders()
                if str(item.get("order_id")) == str(order_id)
            ),
            None,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="Order not found")

        status = str(existing.get("status") or "").upper()
        if status in TERMINAL_ORDER_STATES:
            raise HTTPException(
                status_code=409,
                detail=f"Order is already terminal ({status})",
            )

        account_id = trading._paper_account_id()
        ctx = trading._context()
        try:
            ret, data = ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=str(order_id),
                qty=0,
                price=0,
                trd_env=TrdEnv.SIMULATE,
                acc_id=account_id,
            )
        finally:
            ctx.close()

        if ret != RET_OK:
            raise RuntimeError(str(data))

        trading.clear_cache()
        activity.write(
            category="ORDER",
            action="ORDER_CANCELLED",
            message=f"Cancelled pending PAPER order {order_id}",
            symbol=existing.get("symbol"),
            order_id=str(order_id),
        )

        return {
            "cancelled": True,
            "order_id": str(order_id),
            "previous_status": status,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def build_preview(order: OrderRequest):
    side = order.side.upper()
    order_type = order.order_type.upper()

    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")

    if order_type not in ("MARKET", "LIMIT"):
        raise HTTPException(status_code=400, detail="order_type must be MARKET or LIMIT")

    if order_type == "LIMIT" and order.price is None:
        raise HTTPException(status_code=400, detail="LIMIT order requires price")

    quote = opend.get_snapshot(order.symbol)
    estimated_price = (
        float(order.price)
        if order_type == "LIMIT"
        else float(quote["price"])
    )

    result = risk.evaluate_order(
        trading_enabled=settings.get_bool("trading.enabled"),
        mode=str(settings.get("trading.mode")),
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
        result = build_preview(order)
        activity.write(
            category="ORDER",
            action="ORDER_PREVIEW",
            message=(
                f"Previewed {result['side']} {result['quantity']} "
                f"{result['symbol']} for approximately "
                f"${result['estimated_value']:,.2f}"
            ),
            symbol=result["symbol"]
        )
        activity.write(
            category="RISK",
            action="RISK_APPROVED" if result["approved"] else "RISK_BLOCKED",
            level="INFO" if result["approved"] else "WARN",
            message=(
                "Order approved by risk engine"
                if result["approved"]
                else "Order blocked by risk engine"
            ),
            symbol=result["symbol"]
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/execute")
def execute_order(order: OrderRequest):
    try:
        if str(settings.get("trading.mode")).lower() != "paper":
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

        activity.write(
            category="ORDER",
            action="ORDER_SUBMITTED",
            message=(
                f"Submitted PAPER {preview['side']} "
                f"{preview['quantity']} {preview['symbol']}"
            ),
            symbol=preview["symbol"],
            order_id=str(result.get("order_id", ""))
        )
        activity.write(
            category="BROKER",
            action="ORDER_ACCEPTED",
            message=(
                f"OpenD accepted order {result.get('order_id')} "
                f"with status {result.get('status')}"
            ),
            symbol=preview["symbol"],
            order_id=str(result.get("order_id", ""))
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
        raise HTTPException(status_code=503, detail=str(e))
