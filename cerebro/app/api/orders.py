from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.activity import activity
from app.services.live_safety import live_safety
from app.services.opend import opend
from app.services.risk import risk
from app.services.settings import settings
from app.services.trading import TradeUnlockRequired, trading


router = APIRouter(prefix="/orders", tags=["Orders"])


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


def _unlock_http(exc: Exception):
    raise HTTPException(
        status_code=423,
        detail={
            "code": "TRADE_UNLOCK_REQUIRED",
            "message": str(exc).replace("TRADE_UNLOCK_REQUIRED: ", ""),
        },
    ) from exc


@router.get("/")
def orders():
    try:
        data = trading.get_orders()
        return {
            "count": len(data),
            "mode": trading.mode().upper(),
            "orders": data,
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/{order_id}")
def cancel_pending_order(order_id: str):
    try:
        existing = next(
            (
                item
                for item in trading.get_orders()
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

        trading.cancel_order(order_id)
        account = trading.current_account()
        activity.write(
            category="ORDER",
            action="ORDER_CANCELLED",
            message=f"Cancelled pending {trading.mode().upper()} order {order_id}",
            symbol=existing.get("symbol"),
            order_id=str(order_id),
            details={
                "environment": trading.mode().upper(),
                "account_id": account.get("account_id"),
                "security_firm": account.get("security_firm"),
                "previous_status": status,
            },
        )
        return {
            "cancelled": True,
            "order_id": str(order_id),
            "previous_status": status,
            "mode": trading.mode().upper(),
        }
    except TradeUnlockRequired as exc:
        _unlock_http(exc)
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
    if abs(float(order.quantity) - round(float(order.quantity))) > 1e-9:
        raise HTTPException(status_code=400, detail="Cerebro currently supports whole-share orders only")

    quote = opend.get_snapshot(order.symbol)
    estimated_price = float(order.price) if order_type == "LIMIT" else float(quote["price"])

    account = trading.get_account_summary(refresh=True)
    positions = trading.get_positions(refresh=True)
    position = next(
        (
            item
            for item in positions
            if str(item.get("symbol") or "").upper() == str(quote["symbol"]).upper()
        ),
        None,
    )

    result = risk.evaluate_order(
        trading_enabled=settings.get_bool("trading.enabled"),
        mode=trading.mode(),
        symbol=quote["symbol"],
        side=side,
        quantity=order.quantity,
        estimated_price=estimated_price,
        portfolio_total=float(account.get("total_value") or 0),
        portfolio_cash=float(account.get("cash") or 0),
        portfolio_available_cash=float(
            account.get("available_cash")
            if account.get("available_cash") is not None
            else account.get("cash") or 0
        ),
        portfolio_market_value=float(account.get("market_value") or 0),
        current_position_value=float((position or {}).get("market_value") or 0),
        current_position_qty=float((position or {}).get("quantity") or 0),
        available_position_qty=float((position or {}).get("available_quantity") or 0),
        realized_pnl=account.get("realized_pnl"),
    )

    mode = trading.mode().upper()
    safety_checks = [
        live_safety.market_hours_check(mode=mode, symbol=quote["symbol"]),
        live_safety.cooldown_check(mode=mode, symbol=quote["symbol"], side=side),
    ]
    result = live_safety.apply_checks(result, safety_checks)
    result["order_type"] = order_type
    result["requested_price"] = order.price
    result["account"] = {
        "mode": account.get("mode"),
        "account_id_masked": account.get("account_id_masked"),
        "security_firm": account.get("security_firm"),
        "total_value": account.get("total_value"),
        "cash": account.get("cash"),
        "available_cash": account.get("available_cash"),
    }
    return result


@router.post("/preview")
def preview_order(order: OrderRequest):
    try:
        result = build_preview(order)
        activity.write(
            category="ORDER",
            action="ORDER_PREVIEW",
            message=(
                f"Previewed {result['mode']} {result['side']} {result['quantity']} "
                f"{result['symbol']} for approximately ${result['estimated_value']:,.2f}"
            ),
            symbol=result["symbol"],
            details={
                "environment": result["mode"],
                "account": result.get("account"),
                "approved": result.get("approved"),
                "risk_checks": result.get("risk_checks"),
            },
        )
        activity.write(
            category="RISK",
            action="RISK_APPROVED" if result["approved"] else "RISK_BLOCKED",
            level="INFO" if result["approved"] else "WARN",
            message=(
                f"{result['mode']} order approved by risk engine"
                if result["approved"]
                else f"{result['mode']} order blocked by risk engine"
            ),
            symbol=result["symbol"],
            details={
                "environment": result["mode"],
                "estimated_value": result["estimated_value"],
                "limits": result.get("limits"),
                "failed_checks": [
                    check.get("name")
                    for check in result.get("risk_checks") or []
                    if not check.get("passed")
                ],
            },
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/execute")
def execute_order(order: OrderRequest):
    try:
        # Execution always performs a fresh preview/risk pass. A direct API call
        # therefore cannot bypass account, session, cooldown or risk validation.
        preview = build_preview(order)
        if not preview["approved"]:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Order blocked by risk engine",
                    "preview": preview,
                },
            )

        mode = trading.mode().upper()
        account = trading.current_account(refresh=True)
        result = trading.place_order(
            symbol=preview["symbol"],
            side=preview["side"],
            quantity=preview["quantity"],
            order_type=preview["order_type"],
            price=order.price,
            remark=f"CEREBRO:MANUAL:{mode}",
        )

        activity.write(
            category="ORDER",
            action="ORDER_SUBMITTED",
            message=(
                f"Submitted {mode} {preview['side']} "
                f"{preview['quantity']} {preview['symbol']}"
            ),
            symbol=preview["symbol"],
            order_id=str(result.get("order_id", "")),
            level="WARN" if mode == "LIVE" else "INFO",
            details={
                "environment": mode,
                "account_id": account.get("account_id"),
                "security_firm": account.get("security_firm"),
                "source": "MANUAL",
                "estimated_value": preview.get("estimated_value"),
                "broker_status": result.get("status"),
                "risk_checks": preview.get("risk_checks"),
            },
        )
        activity.write(
            category="BROKER",
            action="ORDER_ACCEPTED",
            message=(
                f"OpenD accepted {mode} order {result.get('order_id')} "
                f"with status {result.get('status')}"
            ),
            symbol=preview["symbol"],
            order_id=str(result.get("order_id", "")),
            level="WARN" if mode == "LIVE" else "INFO",
            details={
                "environment": mode,
                "account_id": account.get("account_id"),
                "security_firm": account.get("security_firm"),
                "source": "MANUAL",
            },
        )

        return {
            "executed": True,
            "mode": mode,
            "preview": preview,
            "order": result,
        }
    except TradeUnlockRequired as exc:
        activity.write(
            category="SECURITY",
            action="TRADE_UNLOCK_REQUIRED",
            message="A live order attempt was paused because trading is locked",
            level="WARN",
            details={"environment": "LIVE", "source": "MANUAL"},
        )
        _unlock_http(exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
