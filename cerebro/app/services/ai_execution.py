from copy import deepcopy

from app.services.ai_memory import ai_memory
from app.services.ai_thesis_store import ai_theses
from app.services.activity import activity
from app.services.opend import opend
from app.services.risk import risk
from app.services.settings import settings
from app.services.trading import trading


ACTIONABLE = {"BUY", "ADD", "REDUCE", "SELL"}
NON_ACTIONABLE = {"HOLD", "WATCH", "IGNORE"}
TERMINAL_ORDER_STATES = {
    "FILLED_ALL",
    "CANCELLED_ALL",
    "CANCELED_ALL",
    "FAILED",
    "DISABLED",
    "DELETED",
}


class AIExecutionService:
    """Translate AI intents into deterministic PAPER order proposals."""

    def _position_map(self, context):
        return {
            str(item.get("symbol")).upper(): item
            for item in (context.get("portfolio", {}).get("positions") or [])
            if item.get("symbol")
        }

    def _candidate_map(self, context):
        return {
            str(item.get("symbol")).upper(): item
            for item in (context.get("candidates") or [])
            if item.get("symbol")
        }

    def _price(self, symbol, position=None):
        try:
            value = float((position or {}).get("current_price"))
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
        snapshot = opend.get_snapshot(symbol)
        value = float(snapshot.get("price") or 0)
        if value <= 0:
            raise RuntimeError(f"No valid market price available for {symbol}")
        return value

    def _has_pending_order(self, symbol, orders):
        symbol = str(symbol).upper()
        return any(
            str(item.get("symbol") or "").upper() == symbol
            and str(item.get("status") or "").upper() not in TERMINAL_ORDER_STATES
            for item in (orders or [])
        )

    def _persist_decision(self, *, item, context, candidate, position, run_id):
        record = ai_memory.create_decision(
            run_id=run_id,
            symbol=item["symbol"],
            action=item["action"],
            strategy="AI_PORTFOLIO",
            confidence=item.get("confidence"),
            target_allocation_pct=item.get("desired_exposure_pct"),
            short_reason=item.get("reasoning") or "AI portfolio decision",
            what_changed=item.get("what_changed"),
            thesis_status="ACTIVE" if item.get("thesis_update") else None,
            invalidation=item.get("thesis_invalidation"),
            market_context=context.get("market_context"),
            portfolio_context={
                "account": context.get("portfolio", {}).get("account"),
                "position": position,
            },
            signals_snapshot={
                "quant": candidate.get("quant"),
                "research_context": candidate.get("research_context"),
            },
        )

        if item.get("thesis_update"):
            ai_theses.replace_active(
                symbol=item["symbol"],
                thesis=item["thesis_update"],
                strategy="AI_PORTFOLIO",
                invalidation=item.get("thesis_invalidation"),
                entry_decision_id=record["id"],
            )
        return record

    def _size(self, *, action, target_pct, total_value, current_value,
              current_qty, price):
        if action == "SELL":
            return "SELL", int(current_qty)
        if target_pct is None:
            raise ValueError(f"{action} requires desired_exposure_pct")

        target_value = total_value * (float(target_pct) / 100.0)
        if action in {"BUY", "ADD"}:
            return "BUY", int(max(0, (target_value - current_value) // price))

        quantity = int(max(0, (current_value - target_value) // price))
        return "SELL", min(quantity, int(current_qty))

    def build(self, *, context, decision_result, memory_run_id=None):
        account = context.get("portfolio", {}).get("account") or {}
        positions = self._position_map(context)
        candidates = self._candidate_map(context)
        pending_orders = context.get("portfolio", {}).get("pending_orders") or []
        total_value = float(account.get("total_value") or 0)
        starting_cash = float(account.get("cash") or 0)
        starting_market_value = float(account.get("market_value") or 0)

        if total_value <= 0:
            raise RuntimeError("Portfolio total value is unavailable; cannot size AI orders")

        max_new_positions = int(settings.get("risk.max_new_positions_per_run"))
        new_positions_used = 0
        projected_cash = starting_cash
        projected_market_value = starting_market_value
        proposals = []

        for raw in decision_result.get("decisions") or []:
            item = deepcopy(raw)
            symbol = str(item.get("symbol") or "").upper()
            action = str(item.get("action") or "").upper()
            item["symbol"] = symbol
            item["action"] = action
            position = positions.get(symbol)
            candidate = candidates.get(symbol) or {}

            record = self._persist_decision(
                item=item,
                context=context,
                candidate=candidate,
                position=position,
                run_id=memory_run_id,
            )

            proposal = {
                "decision_id": record["id"],
                "symbol": symbol,
                "action": action,
                "confidence": item.get("confidence"),
                "reasoning": item.get("reasoning"),
                "what_changed": item.get("what_changed"),
                "thesis_update": item.get("thesis_update"),
                "thesis_invalidation": item.get("thesis_invalidation"),
                "desired_exposure_pct": item.get("desired_exposure_pct"),
                "status": "NO_ORDER",
                "order": None,
                "risk": None,
                "message": None,
            }

            if action in NON_ACTIONABLE:
                ai_memory.set_execution_result(record["id"], status="DEFERRED")
                proposal["message"] = f"{action} requires no broker order"
                proposals.append(proposal)
                continue

            if action not in ACTIONABLE:
                ai_memory.set_execution_result(
                    record["id"], status="REJECTED",
                    rejection_code="INVALID_ACTION",
                    rejection_reason=f"Unsupported actionable decision: {action}",
                )
                proposal["status"] = "BLOCKED"
                proposal["message"] = "Unsupported actionable decision"
                proposals.append(proposal)
                continue

            if self._has_pending_order(symbol, pending_orders):
                proposal["status"] = "BLOCKED"
                proposal["message"] = "Existing pending broker order prevents a duplicate AI order"
                ai_memory.set_execution_result(
                    record["id"], status="REJECTED",
                    rejection_code="PENDING_ORDER_EXISTS",
                    rejection_reason=proposal["message"],
                )
                proposals.append(proposal)
                continue

            price = self._price(symbol, position)
            current_qty = float(
                (position or {}).get("available_quantity")
                or (position or {}).get("quantity")
                or 0
            )
            current_value = float((position or {}).get("market_value") or 0)
            target_pct = item.get("desired_exposure_pct")

            try:
                side, quantity = self._size(
                    action=action,
                    target_pct=target_pct,
                    total_value=total_value,
                    current_value=current_value,
                    current_qty=current_qty,
                    price=price,
                )
            except ValueError as exc:
                proposal["status"] = "BLOCKED"
                proposal["message"] = str(exc)
                ai_memory.set_execution_result(
                    record["id"], status="REJECTED",
                    rejection_code="MISSING_TARGET_EXPOSURE",
                    rejection_reason=proposal["message"],
                )
                proposals.append(proposal)
                continue

            if quantity <= 0:
                proposal["message"] = "Target exposure does not require a whole-share order"
                ai_memory.set_execution_result(record["id"], status="DEFERRED")
                proposals.append(proposal)
                continue

            if action == "BUY" and new_positions_used >= max_new_positions:
                proposal["status"] = "BLOCKED"
                proposal["message"] = f"Maximum new positions per run ({max_new_positions}) reached"
                ai_memory.set_execution_result(
                    record["id"], status="REJECTED",
                    rejection_code="MAX_NEW_POSITIONS",
                    rejection_reason=proposal["message"],
                )
                proposals.append(proposal)
                continue

            order_type = str(settings.get("execution.default_order_type") or "MARKET").upper()
            order = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "price": price if order_type == "LIMIT" else None,
                "estimated_price": price,
            }
            metrics = ((candidate.get("quant") or {}).get("metrics") or {})
            median_turnover = metrics.get("median_turnover_60d")
            proposal["median_turnover_60d"] = median_turnover

            risk_result = risk.evaluate_order(
                trading_enabled=settings.get_bool("trading.enabled"),
                mode=str(settings.get("trading.mode")),
                symbol=symbol,
                side=side,
                quantity=quantity,
                estimated_price=price,
                portfolio_total=total_value,
                portfolio_cash=projected_cash,
                portfolio_market_value=projected_market_value,
                current_position_value=current_value,
                median_turnover_60d=median_turnover,
            )
            proposal["order"] = order
            proposal["risk"] = risk_result

            if not risk_result.get("approved"):
                proposal["status"] = "BLOCKED"
                proposal["message"] = "Blocked by deterministic risk engine"
                ai_memory.set_execution_result(
                    record["id"], status="REJECTED",
                    rejection_code="RISK_BLOCKED",
                    rejection_reason=proposal["message"],
                )
            else:
                proposal["status"] = "PENDING_APPROVAL"
                proposal["message"] = "Ready for manual approval"
                ai_memory.set_execution_result(record["id"], status="DEFERRED")

                reserved_value = float(risk_result.get("estimated_value") or 0)
                if side == "BUY":
                    projected_cash -= reserved_value
                    projected_market_value += reserved_value
                else:
                    projected_cash += reserved_value
                    projected_market_value = max(0.0, projected_market_value - reserved_value)
                if action == "BUY":
                    new_positions_used += 1

            proposals.append(proposal)

        return {
            "auto_execute": settings.get_bool("execution.auto_execute"),
            "proposals": proposals,
            "persisted_decision_count": len(proposals),
            "projected_portfolio": {
                "cash": round(projected_cash, 2),
                "market_value": round(projected_market_value, 2),
            },
        }

    def _fresh_execution_order(self, proposal):
        symbol = proposal["symbol"]
        action = proposal["action"]

        if self._has_pending_order(symbol, trading.get_orders()):
            raise RuntimeError(
                f"A pending broker order already exists for {symbol}; duplicate execution blocked"
            )

        account = trading.get_account_summary(refresh=True)
        positions = trading.get_positions(refresh=True)
        position = next(
            (item for item in positions if str(item.get("symbol") or "").upper() == symbol),
            None,
        )
        total_value = float(account.get("total_value") or 0)
        if total_value <= 0:
            raise RuntimeError("Fresh portfolio value is unavailable")

        price = self._price(symbol)
        current_qty = float(
            (position or {}).get("available_quantity")
            or (position or {}).get("quantity")
            or 0
        )
        current_value = float((position or {}).get("market_value") or 0)
        side, quantity = self._size(
            action=action,
            target_pct=proposal.get("desired_exposure_pct"),
            total_value=total_value,
            current_value=current_value,
            current_qty=current_qty,
            price=price,
        )
        if quantity <= 0:
            raise RuntimeError("Target exposure no longer requires a whole-share order")

        order_type = str(settings.get("execution.default_order_type") or "MARKET").upper()
        fresh_risk = risk.evaluate_order(
            trading_enabled=settings.get_bool("trading.enabled"),
            mode=str(settings.get("trading.mode")),
            symbol=symbol,
            side=side,
            quantity=quantity,
            estimated_price=price,
            portfolio_total=total_value,
            portfolio_cash=float(account.get("cash") or 0),
            portfolio_market_value=float(account.get("market_value") or 0),
            current_position_value=current_value,
            median_turnover_60d=proposal.get("median_turnover_60d"),
        )
        if not fresh_risk.get("approved"):
            failed_checks = [
                check.get("message")
                for check in fresh_risk.get("risk_checks") or []
                if not check.get("passed")
            ]
            raise RuntimeError(
                "Fresh risk check blocked execution: " + "; ".join(failed_checks)
            )

        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "price": price if order_type == "LIMIT" else None,
            "estimated_price": price,
        }, fresh_risk

    def execute(self, proposal):
        if proposal.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
            raise RuntimeError("Proposal is not executable")
        if str(settings.get("trading.mode")).lower() != "paper":
            raise RuntimeError("AI execution is limited to paper trading")

        decision_id = proposal.get("decision_id")
        order, fresh_risk = self._fresh_execution_order(proposal)
        ai_memory.set_execution_result(decision_id, status="APPROVED")

        broker = trading.place_paper_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            price=order.get("price"),
        )
        ai_memory.set_execution_result(
            decision_id,
            status="EXECUTED",
            broker_status=str(broker.get("status")),
            order_id=str(broker.get("order_id")),
        )

        if proposal.get("action") == "SELL":
            ai_theses.close_active(
                symbol=order["symbol"],
                closing_decision_id=decision_id,
                reason="Position exited by AI SELL decision",
            )

        activity.write(
            category="AI",
            action="AI_ORDER_EXECUTED",
            message=(
                f"AI decision {decision_id} executed {order['side']} "
                f"{order['quantity']} {order['symbol']}"
            ),
            symbol=order["symbol"],
            order_id=str(broker.get("order_id", "")),
        )

        result = deepcopy(proposal)
        result["status"] = "EXECUTED"
        result["order"] = order
        result["risk"] = fresh_risk
        result["broker_order"] = broker
        result["message"] = "Paper order submitted after fresh risk validation"
        return result

    def reject(self, proposal, reason="Rejected by user"):
        if proposal.get("status") != "PENDING_APPROVAL":
            raise RuntimeError("Proposal is not awaiting approval")
        ai_memory.set_execution_result(
            proposal["decision_id"],
            status="REJECTED",
            rejection_code="USER_REJECTED",
            rejection_reason=reason,
        )
        result = deepcopy(proposal)
        result["status"] = "REJECTED"
        result["message"] = reason
        return result


ai_execution = AIExecutionService()
