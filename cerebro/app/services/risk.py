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
        portfolio_available_cash: float | None = None,
        portfolio_market_value: float | None = None,
        current_position_value: float | None = None,
        current_position_qty: float | None = None,
        available_position_qty: float | None = None,
        median_turnover_60d: float | None = None,
        realized_pnl: float | None = None,
    ):
        enabled = settings.get_bool("risk.enabled")
        configured_max_order_value = float(settings.get("risk.max_order_value"))
        max_daily_loss = float(settings.get("risk.max_daily_loss"))
        max_position_pct = float(settings.get("risk.max_position_pct"))
        max_invested_pct = float(settings.get("risk.max_invested_pct"))
        min_cash_reserve_pct = float(settings.get("risk.min_cash_reserve_pct"))
        max_order_adv_pct = float(settings.get("risk.max_order_adv_pct"))

        mode = str(mode or "paper").upper()
        side = str(side).upper()
        quantity = float(quantity)
        estimated_price = float(estimated_price)
        estimated_value = round(quantity * estimated_price, 2)
        checks = []

        checks.append({
            "name": "risk_engine_enabled",
            "passed": enabled,
            "message": "Risk engine enabled" if enabled else "Risk engine is disabled",
        })
        checks.append({
            "name": "trading_enabled",
            "passed": bool(trading_enabled),
            "message": "Trading execution enabled" if trading_enabled else "Trading execution is disabled",
        })
        checks.append({
            "name": "execution_environment",
            "passed": mode in {"PAPER", "LIVE"},
            "message": f"{mode} execution environment" if mode in {"PAPER", "LIVE"} else f"Unsupported execution mode {mode}",
        })
        checks.append({
            "name": "valid_quantity",
            "passed": quantity > 0 and abs(quantity - round(quantity)) < 1e-9,
            "message": (
                "Whole-share quantity is valid"
                if quantity > 0 and abs(quantity - round(quantity)) < 1e-9
                else "Quantity must be a positive whole-share amount"
            ),
        })

        effective_order_limit = configured_max_order_value
        if portfolio_total is not None and float(portfolio_total or 0) > 0 and side == "BUY":
            portfolio_scaled_limit = float(portfolio_total) * max_position_pct / 100.0
            effective_order_limit = min(configured_max_order_value, portfolio_scaled_limit)

        checks.append({
            "name": "max_order_value",
            "passed": estimated_value <= effective_order_limit + 1e-9,
            "message": (
                f"Estimated order value ${estimated_value:,.2f} is within ${effective_order_limit:,.2f} effective limit"
                if estimated_value <= effective_order_limit + 1e-9
                else f"Estimated order value ${estimated_value:,.2f} exceeds ${effective_order_limit:,.2f} effective limit"
            ),
        })

        total = float(portfolio_total or 0)
        cash = float(portfolio_cash or 0)
        available_cash = float(portfolio_available_cash if portfolio_available_cash is not None else cash)
        market_value = float(portfolio_market_value or 0)
        current_value = float(current_position_value or 0)
        current_qty = float(current_position_qty or 0)
        available_qty = float(available_position_qty if available_position_qty is not None else current_qty)

        if side == "SELL":
            checks.append({
                "name": "long_only_sell",
                "passed": quantity <= available_qty + 1e-9 and available_qty > 0,
                "message": (
                    f"Sell quantity {quantity:g} is within {available_qty:g} available shares"
                    if quantity <= available_qty + 1e-9 and available_qty > 0
                    else f"Sell quantity {quantity:g} exceeds {available_qty:g} available shares; short selling is blocked"
                ),
            })

        if total > 0:
            projected_position = current_value + estimated_value if side == "BUY" else max(0.0, current_value - estimated_value)
            projected_position_pct = projected_position / total * 100.0
            checks.append({
                "name": "max_position_pct",
                "passed": projected_position_pct <= max_position_pct + 1e-9,
                "message": (
                    f"Projected position {projected_position_pct:.2f}% is within {max_position_pct:.2f}% limit"
                    if projected_position_pct <= max_position_pct + 1e-9
                    else f"Projected position {projected_position_pct:.2f}% exceeds {max_position_pct:.2f}% limit"
                ),
            })

            projected_market_value = market_value + estimated_value if side == "BUY" else max(0.0, market_value - estimated_value)
            projected_invested_pct = projected_market_value / total * 100.0
            checks.append({
                "name": "max_invested_pct",
                "passed": projected_invested_pct <= max_invested_pct + 1e-9,
                "message": (
                    f"Projected invested capital {projected_invested_pct:.2f}% is within {max_invested_pct:.2f}% limit"
                    if projected_invested_pct <= max_invested_pct + 1e-9
                    else f"Projected invested capital {projected_invested_pct:.2f}% exceeds {max_invested_pct:.2f}% limit"
                ),
            })

            projected_cash = cash - estimated_value if side == "BUY" else cash + estimated_value
            projected_cash_pct = projected_cash / total * 100.0
            checks.append({
                "name": "min_cash_reserve_pct",
                "passed": projected_cash_pct + 1e-9 >= min_cash_reserve_pct,
                "message": (
                    f"Projected cash reserve {projected_cash_pct:.2f}% meets {min_cash_reserve_pct:.2f}% minimum"
                    if projected_cash_pct + 1e-9 >= min_cash_reserve_pct
                    else f"Projected cash reserve {projected_cash_pct:.2f}% is below {min_cash_reserve_pct:.2f}% minimum"
                ),
            })

        if side == "BUY":
            checks.append({
                "name": "available_cash",
                "passed": estimated_value <= available_cash + 1e-9,
                "message": (
                    f"Order fits available funds (${available_cash:,.2f})"
                    if estimated_value <= available_cash + 1e-9
                    else f"Order value ${estimated_value:,.2f} exceeds available funds ${available_cash:,.2f}"
                ),
            })

        if realized_pnl is not None and max_daily_loss > 0:
            try:
                realized = float(realized_pnl)
            except (TypeError, ValueError):
                realized = 0.0
            loss_ok = realized > -max_daily_loss
            checks.append({
                "name": "realized_loss_guard",
                "passed": loss_ok,
                "message": (
                    f"Broker realized P&L ${realized:,.2f} is above the -${max_daily_loss:,.2f} loss guard"
                    if loss_ok
                    else f"Broker realized P&L ${realized:,.2f} breaches the -${max_daily_loss:,.2f} loss guard"
                ),
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
                    ),
                })

        approved = all(check["passed"] for check in checks)
        return {
            "approved": approved,
            "mode": mode,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "estimated_price": estimated_price,
            "estimated_value": estimated_value,
            "projected": {
                "cash": (cash - estimated_value if side == "BUY" else cash + estimated_value) if total > 0 else None,
                "position_value": current_value + estimated_value if side == "BUY" else max(0.0, current_value - estimated_value),
            },
            "limits": {
                "configured_max_order_value": configured_max_order_value,
                "effective_max_order_value": effective_order_limit,
                "max_daily_loss": max_daily_loss,
                "max_position_pct": max_position_pct,
                "max_invested_pct": max_invested_pct,
                "min_cash_reserve_pct": min_cash_reserve_pct,
                "max_order_adv_pct": max_order_adv_pct,
            },
            "risk_checks": checks,
        }


risk = RiskEngine()
