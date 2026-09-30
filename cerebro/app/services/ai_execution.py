from copy import deepcopy

from app.services.ai_memory import ai_memory
from app.services.ai_thesis_store import ai_theses
from app.services.activity import activity
from app.services.opend import opend
from app.services.risk import risk
from app.services.settings import settings
from app.services.trading import trading


ACTIONABLE = {"BUY", "ADD", "REDUCE", "SELL"}
NON_ACTIONABLE = {"HOLD", "WATCH"}


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

    def _price(self, symbol, position):
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

    def build(self, *, context, decision_result, memory_run_id=None):
        account = context.get("portfolio", {}).get("account") or {}
        positions = self._position_map(context)
        candidates = self._candidate_map(context)
        total_value = float(account.get("total_value") or 0)
        cash = float(account.get("cash") or 0)
        market_value = float(account.get("market_value") or 0)

        if total_value <= 0:
            raise RuntimeError("Portfolio total value is unavailable; cannot size AI orders")

        max_new_positions = int(settings.get("risk.max_new_positions_per_run"))
        new_positions_used = 0
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
                    record["id"],
                    status="REJECTED",
                    rejection_code="INVALID_ACTION",
                    rejection_reason=f"Unsupported actionable decision: {action}",
                )
                proposal["status"] = "BLOCKED"
                proposal["message"] = "Unsupported actionable decision"
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

            if action == "SELL":
                side = "SELL"
                quantity = int(current_qty)
            else:
                if target_pct is None:
                    proposal["status"] = "BLOCKED"
                    proposal["message"] = f"{action} requires desired_exposure_pct for deterministic sizing"
                    ai_memory.set_execution_result(
                        record["id"],
                        status="REJECTED",
                        rejection_code="MISSING_TARGET_EXPOSURE",
                        rejection_reason=proposal["message"],
                    )
                    proposals.append(proposal)
                    continue

                target_value = total_value * (float(target_pct) / 100.0)
                if action in {"BUY", "ADD"}:
                    side = "BUY"
                    quantity = int(max(0, (target_value - current_value) // price))
                else:
                    side = "SELL"
                    quantity = int(max(0, (current_value - target_value) // price))
                    quantity = min(quantity, int(current_qty))

            if quantity <= 0:
                proposal["message"] = "Target exposure does not require a whole-share order"
                ai_memory.set_execution_result(record["id"], status="DEFERRED")
                proposals.append(proposal)
                continue

            if action == "BUY":
                if new_positions_used >= max_new_positions:
                    proposal["status"] = "BLOCKED"
                    proposal["message"] = f"Maximum new positions per run ({max_new_positions}) reached"
                    ai_memory.set_execution_result(
                        record["id"],
                        status="REJECTED",
                        rejection_code="MAX_NEW_POSITIONS",
                        rejection_reason=proposal["message"],
                    )
                    proposals.append(proposal)
                    continue
                new_positions_used += 1

            order = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "order_type": str(settings.get("execution.default_order_type")),
                "price": None,
                "estimated_price": price,
            }
            metrics = ((candidate.get("quant") or {}).get("metrics") or {})
            risk_result = risk.evaluate_order(
                trading_enabled=settings.get_bool("trading.enabled"),
                mode=str(settings.get("trading.mode")),
                symbol=symbol,
                side=side,
                quantity=quantity,
                estimated_price=price,
                portfolio_total=total_value,
                portfolio_cash=cash,
                portfolio_market_value=market_value,
                current_position_value=current_value,
                median_turnover_60d=metrics.get("median_turnover_60d"),
            )
            proposal["order"] = order
            proposal["risk"] = risk_result

            if not risk_result.get("approved"):
                proposal["status"] = "BLOCKED"
                proposal["message"] = "Blocked by deterministic risk engine"
                ai_memory.set_execution_result(
                    record["id"],
                    status="REJECTED",
                    rejection_code="RISK_BLOCKED",
                    rejection_reason=proposal["message"],
                )
            else:
                proposal["status"] = "PENDING_APPROVAL"
                proposal["message"] = "Ready for manual approval"
                ai_memory.set_execution_result(record["id"], status="DEFERRED")

            proposals.append(proposal)

        return {
            "auto_execute": settings.get_bool("execution.auto_execute"),
            "proposals": proposals,
            "persisted_decision_count": len(proposals),
        }

    def execute(self, proposal):
        if proposal.get("status") not in {"PENDING_APPROVAL", "APPROVED"}:
            raise RuntimeError("Proposal is not executable")
        if str(settings.get("trading.mode")).lower() != "paper":
            raise RuntimeError("AI execution is limited to paper trading")
        risk_result = proposal.get("risk") or {}
        if not risk_result.get("approved"):
            raise RuntimeError("Proposal is not approved by the risk engine")

        order = proposal.get("order") or {}
        decision_id = proposal.get("decision_id")
        ai_memory.set_execution_result(decision_id, status="APPROVED")

        broker = trading.place_paper_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            order_type=order.get("order_type") or "MARKET",
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
        result["broker_order"] = broker
        result["message"] = "Paper order submitted"
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
