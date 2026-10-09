"""Keep broker integer identifiers lossless across JSON/browser boundaries."""
import math


def broker_id(value):
    if hasattr(value, "item"):
        value = value.item()
    if value is None or str(value) in {"", "N/A", "nan"}:
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer() or abs(value) > 2**53 - 1:
            raise ValueError("Broker returned an unsafe numeric identifier")
        value = int(value)
    return str(value)


def masked_id(value):
    text = broker_id(value)
    return f"••••{text[-4:]}" if text else None
