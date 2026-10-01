"""USD securities-account fields; futures funds/P&L are deliberately excluded."""
import math


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def securities_funds(row):
    def pick(*fields):
        for field in fields:
            value = number(row.get(field))
            if value is not None:
                return value, field
        return None, None

    total, total_source = pick("usd_assets", "total_assets")
    cash, cash_source = pick("us_cash", "cash")
    power, power_source = pick("usd_net_cash_power")
    # Missing buying-power data is unknown, not permission to spend all cash.
    available = max(0.0, min(cash, power)) if cash is not None and power is not None else None
    return {
        "total_value": total, "cash": cash,
        "market_value": number(row.get("market_val")),
        "available_cash": available, "available_funds": available,
        "cash_buying_power": power, "buying_power": power,
        "funds_verified": available is not None,
        "field_sources": {
            "total_value": total_source, "cash": cash_source,
            "market_value": "market_val (query currency USD)",
            "cash_buying_power": power_source,
            "available_cash": "max(0, min(USD cash, USD cash buying power))",
        },
    }


def position_pnl(positions):
    def aggregate(field):
        values = [number(p.get(field)) if p.get("currency") in (None, "USD") else None for p in positions]
        return round(sum(values), 6) if all(v is not None for v in values) else None
    return {
        "position_pnl": aggregate("profit_loss"),
        "unrealized_pnl": aggregate("unrealized_pnl"),
        "today_position_pnl": aggregate("today_pnl"),
        # Current positions cannot establish lifetime realized P&L of closed holdings.
        "realized_pnl": None,
        "pnl_sources": {"position_pnl": "sum(position.pl_val), valid USD positions only",
                        "unrealized_pnl": "sum(position.unrealized_pl), average-cost basis",
                        "today_position_pnl": "sum(position.today_pl_val)",
                        "realized_pnl": "Unavailable: requires verified closed-trade history"},
    }


def account_context(account):
    keys = ("mode", "currency", "account_id_masked", "security_firm", "execution_context_id",
            "total_value", "cash", "market_value", "available_cash", "available_funds",
            "cash_buying_power", "funds_verified", "field_sources", "position_pnl",
            "unrealized_pnl", "realized_pnl", "today_position_pnl", "daily_pnl",
            "daily_pnl_method", "daily_pnl_baseline", "pnl_sources")
    return {key: account.get(key) for key in keys}
