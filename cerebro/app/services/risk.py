from app.services.settings import settings


class RiskEngine:

    def evaluate_order(
        self,
        *,
        trading_enabled: bool,
        mode: str,
        symbol: str,
        side: str,
        quantity: float,
        estimated_price: float
    ):
        # Read on every evaluation so UI changes apply without a restart.
        enabled = settings.get_bool("risk.enabled")
        max_order_value = float(settings.get("risk.max_order_value"))
        max_daily_loss = float(settings.get("risk.max_daily_loss"))

        checks = []
        estimated_value = round(quantity * estimated_price, 2)

        checks.append({
            "name": "risk_engine_enabled",
            "passed": enabled,
            "message": (
                "Risk engine enabled"
                if enabled
                else "Risk engine is disabled"
            )
        })

        checks.append({
            "name": "trading_enabled",
            "passed": bool(trading_enabled),
            "message": (
                "Trading execution enabled"
                if trading_enabled
                else "Trading execution is disabled"
            )
        })

        checks.append({
            "name": "valid_quantity",
            "passed": quantity > 0,
            "message": (
                "Quantity is valid"
                if quantity > 0
                else "Quantity must be greater than zero"
            )
        })

        checks.append({
            "name": "max_order_value",
            "passed": estimated_value <= max_order_value,
            "message": (
                f"Estimated order value ${estimated_value:,.2f} "
                f"is within ${max_order_value:,.2f} limit"
                if estimated_value <= max_order_value
                else
                f"Estimated order value ${estimated_value:,.2f} "
                f"exceeds ${max_order_value:,.2f} limit"
            )
        })

        approved = all(check["passed"] for check in checks)

        return {
            "approved": approved,
            "mode": mode.upper(),
            "symbol": symbol,
            "side": side.upper(),
            "quantity": quantity,
            "estimated_price": estimated_price,
            "estimated_value": estimated_value,
            "limits": {
                "max_order_value": max_order_value,
                "max_daily_loss": max_daily_loss,
            },
            "risk_checks": checks,
        }


risk = RiskEngine()
