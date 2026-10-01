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
        estimated_price: float,
        portfolio_total: float | None = None,
        portfolio_cash: float | None = None,
        portfolio_market_value: float | None = None,
        current_position_value: float | None = None,
        median_turnover_60d: float | None = None,
    ):
        enabled = settings.get_bool("risk.enabled")
        max_order_value = float(settings.get("risk.max_order_value"))
        max_daily_loss = float(settings.get("risk.max_daily_loss"))
        max_position_pct = float(settings.get("risk.max_position_pct"))
        max_invested_pct = float(settings.get("risk.max_invested_pct"))
        min_cash_reserve_pct = float(settings.get("risk.min_cash_reserve_pct"))
        max_order_adv_pct = float(settings.get("risk.max_order_adv_pct"))

        checks = []
        estimated_value = round(float(quantity) * float(estimated_price), 2)
        side = side.upper()

        checks.append({
            "name": "risk_engine_enabled",
            "passed": enabled,
            "message": "Risk engine enabled" if enabled else "Risk engine is disabled"
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
            "name": "paper_mode_only",
            "passed": str(mode).lower() == "paper",
            "message": (
                "Paper execution mode"
                if str(mode).lower() == "paper"
                else "Live trading is not implemented"
            )
        })
        checks.append({
            "name": "valid_quantity",
            "passed": quantity > 0,
            "message": "Quantity is valid" if quantity > 0 else "Quantity must be greater than zero"
        })
        checks.append({
            "name": "max_order_value",
            "passed": estimated_value <= max_order_value,
            "message": (
                f"Estimated order value ${estimated_value:,.2f} is within ${max_order_value:,.2f} limit"
                if estimated_value <= max_order_value
                else f"Estimated order value ${estimated_value:,.2f} exceeds ${max_order_value:,.2f} limit"
            )
        })

        if portfolio_total and portfolio_total > 0:
            current_value = float(current_position_value or 0)
            market_value = float(portfolio_market_value or 0)
            cash = float(portfolio_cash or 0)

            projected_position = (
                current_value + estimated_value
                if side == "BUY"
                else max(0.0, current_value - estimated_value)
            )
            projected_position_pct = projected_position / portfolio_total * 100.0
            checks.append({
                "name": "max_position_pct",
                "passed": projected_position_pct <= max_position_pct + 1e-9,
                "message": (
                    f"Projected position {projected_position_pct:.2f}% is within {max_position_pct:.2f}% limit"
                    if projected_position_pct <= max_position_pct + 1e-9
                    else f"Projected position {projected_position_pct:.2f}% exceeds {max_position_pct:.2f}% limit"
                )
            })

            projected_market_value = (
                market_value + estimated_value
                if side == "BUY"
                else max(0.0, market_value - estimated_value)
            )
            projected_invested_pct = projected_market_value / portfolio_total * 100.0
            checks.append({
                "name": "max_invested_pct",
                "passed": projected_invested_pct <= max_invested_pct + 1e-9,
                "message": (
                    f"Projected invested capital {projected_invested_pct:.2f}% is within {max_invested_pct:.2f}% limit"
                    if projected_invested_pct <= max_invested_pct + 1e-9
                    else f"Projected invested capital {projected_invested_pct:.2f}% exceeds {max_invested_pct:.2f}% limit"
                )
            })

            projected_cash = cash - estimated_value if side == "BUY" else cash + estimated_value
            projected_cash_pct = projected_cash / portfolio_total * 100.0
            checks.append({
                "name": "min_cash_reserve_pct",
                "passed": projected_cash_pct + 1e-9 >= min_cash_reserve_pct,
                "message": (
                    f"Projected cash reserve {projected_cash_pct:.2f}% meets {min_cash_reserve_pct:.2f}% minimum"
                    if projected_cash_pct + 1e-9 >= min_cash_reserve_pct
                    else f"Projected cash reserve {projected_cash_pct:.2f}% is below {min_cash_reserve_pct:.2f}% minimum"
                )
            })

        if median_turnover_60d is not None:
            try:
                adv_value = float(median_turnover_60d)
            except (TypeError, ValueError):
                adv_value = 0.0
            if adv_value > 0:
                order_adv_pct = estimated_value / adv_value * 100.0
                checks.append({
                    "name": "max_order_adv_pct",
                    "passed": order_adv_pct <= max_order_adv_pct + 1e-9,
                    "message": (
                        f"Order is {order_adv_pct:.3f}% of 60-day median turnover, within {max_order_adv_pct:.2f}% limit"
                        if order_adv_pct <= max_order_adv_pct + 1e-9
                        else f"Order is {order_adv_pct:.3f}% of 60-day median turnover, above {max_order_adv_pct:.2f}% limit"
                    )
                })

        approved = all(check["passed"] for check in checks)
        return {
            "approved": approved,
            "mode": str(mode).upper(),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "estimated_price": estimated_price,
            "estimated_value": estimated_value,
            "limits": {
                "max_order_value": max_order_value,
                "max_daily_loss": max_daily_loss,
                "max_position_pct": max_position_pct,
                "max_invested_pct": max_invested_pct,
                "min_cash_reserve_pct": min_cash_reserve_pct,
                "max_order_adv_pct": max_order_adv_pct,
            },
            "risk_checks": checks,
        }


risk = RiskEngine()
