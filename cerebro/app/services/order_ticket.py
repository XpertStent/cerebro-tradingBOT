"""Validate the manual ticket before broker access, including direct API calls."""
import math

ORDER_TYPES = {"MARKET": "MARKET", "LIMIT": "NORMAL", "STOP": "STOP", "STOP_LIMIT": "STOP_LIMIT"}
CONDITIONAL_TYPES = {"STOP", "STOP_LIMIT"}
LIMIT_TYPES = {"LIMIT", "STOP_LIMIT"}


def positive(value, label):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a positive number") from None
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return result


def validate_ticket(*, mode, side, order_type, price=None, trigger_price=None, time_in_force="DAY", quantity=None, market_price=None):
    mode, side, order_type, tif = (str(value).upper() for value in (mode, side, order_type, time_in_force))
    if mode not in {"LIVE", "PAPER"}:
        raise ValueError("Unsupported trading environment")
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if order_type not in ORDER_TYPES:
        raise ValueError("Unsupported order type")
    if tif not in {"DAY", "GTC"}:
        raise ValueError("Time-in-force must be DAY or GTC")
    if mode != "LIVE" and (order_type in CONDITIONAL_TYPES or tif != "DAY"):
        raise ValueError("Conditional orders and GTC are available only in LIVE mode")
    if quantity is not None:
        qty = positive(quantity, "Quantity")
        if not qty.is_integer():
            raise ValueError("Cerebro currently supports whole-share orders only")
    px = positive(price, "Limit price") if order_type in LIMIT_TYPES else None
    trigger = positive(trigger_price, "Trigger price") if order_type in CONDITIONAL_TYPES else None
    if order_type not in LIMIT_TYPES and price is not None:
        raise ValueError("This order type does not use a limit price")
    if order_type not in CONDITIONAL_TYPES and trigger_price is not None:
        raise ValueError("This order type does not use a trigger price")
    current = positive(market_price, "Current market price") if market_price is not None else None
    if trigger is not None and current is not None:
        if side == "BUY" and trigger <= current:
            raise ValueError("BUY stop trigger must be above the current market price")
        if side == "SELL" and trigger >= current:
            raise ValueError("SELL stop trigger must be below the current market price")
    estimate = px if px is not None else (max(current, trigger) if current is not None and trigger is not None else current or trigger)
    return {"order_type": order_type, "side": side, "price": px, "trigger_price": trigger, "time_in_force": tif, "estimated_price": estimate}
