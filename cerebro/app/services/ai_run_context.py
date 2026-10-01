from datetime import datetime, timezone

from app.services.ai_context import ai_context
from app.services.ai_research_batches import ai_research_batches
from app.services.opend import opend
from app.services.trading import trading
from app.services.watchlist import watchlist
from app.services.latest_quant import latest_quant
from app.services.settings import settings


class AIRunContextBuilder:

    def _compact_position(self, item):
        keys = [
            "symbol", "name", "quantity", "qty", "available_qty",
            "average_cost", "avg_cost", "current_price", "market_value",
            "unrealized_pnl", "unrealized_pnl_pct", "profit_loss", "profit_loss_percent",
            "available_quantity", "today_pnl", "currency",
        ]
        return {key: item.get(key) for key in keys if item.get(key) is not None}

    def _compact_order(self, item):
        keys = [
            "order_id", "symbol", "side", "quantity", "qty", "order_type",
            "price", "status", "filled_qty",
        ]
        return {key: item.get(key) for key in keys if item.get(key) is not None}

    def _market_context(self):
        raw = opend.get_market_states()
        if isinstance(raw, list):
            states = raw
        elif isinstance(raw, dict):
            states = (
                raw.get("markets") or raw.get("states") or
                raw.get("market_states") or raw.get("data") or []
            )
            if isinstance(states, dict):
                states = [
                    {"market": key, "state": value}
                    for key, value in states.items()
                ]
        else:
            states = []

        us = None
        for item in states:
            if not isinstance(item, dict):
                continue
            market = str(
                item.get("market") or item.get("id") or item.get("code") or
                item.get("name") or ""
            ).upper()
            if market == "US":
                us = item
                break

        return {
            "market": "US",
            "timezone": "America/New_York",
            "state": us,
        }

    def _risk_policy(self):
        """Expose deterministic limits to the model without weakening them."""
        return {
            "risk_engine_enabled": settings.get_bool("risk.enabled"),
            "trading_enabled": settings.get_bool("trading.enabled"),
            "trading_mode": str(settings.get("trading.mode")),
            "max_order_value_usd": float(settings.get("risk.max_order_value")),
            "max_daily_loss_usd": float(settings.get("risk.max_daily_loss")),
            "max_position_pct": float(settings.get("risk.max_position_pct")),
            "max_invested_pct": float(settings.get("risk.max_invested_pct")),
            "min_cash_reserve_pct": float(settings.get("risk.min_cash_reserve_pct")),
            "max_new_positions_per_run": int(settings.get("risk.max_new_positions_per_run")),
            "max_order_adv_pct": float(settings.get("risk.max_order_adv_pct")),
            "default_order_type": str(settings.get("execution.default_order_type")),
            "auto_execute": settings.get_bool("execution.auto_execute"),
            "execution_boundary": "PAPER_ONLY",
            "sizing_note": (
                "desired_exposure_pct is converted to whole shares and the resulting order "
                "must satisfy every deterministic limit above."
            ),
        }

    def _market_snapshots(self, symbols):
        symbols = [symbol for symbol in symbols if symbol]
        if not symbols:
            return {}
        try:
            rows = opend.get_snapshots(symbols)
        except Exception:
            return {}
        return {
            str(item.get("symbol") or "").upper(): item
            for item in rows
            if item.get("symbol")
        }

    def build(
        self,
        *,
        run_type="MANUAL",
        max_candidates=None,
        enrich_research=None,
        research_progress_callback=None,
    ):
        """Build deterministic decision context with clustered live research."""

        if max_candidates is None:
            max_candidates = int(settings.get("ai.context.max_candidates"))
        if enrich_research is None:
            enrich_research = settings.get_bool("ai.research.enabled")

        decision_limit = int(settings.get("ai.context.recent_decisions_per_symbol"))
        rejection_limit = int(settings.get("ai.context.recent_rejections_per_symbol"))
        include_watchlist = settings.get_bool("ai.context.include_watchlist")

        account = trading.get_account_summary(refresh=True)
        positions_raw = trading.get_positions()
        orders_raw = trading.get_orders()

        watch_items = []
        if include_watchlist:
            watch_items = [
                item for item in watchlist.list()
                if item.get("enabled", True)
                and str(item.get("market") or "").upper() in {"", "US"}
                and str(item.get("symbol", "")).upper().startswith("US.")
            ]
        watch_by_symbol = {
            str(item.get("symbol") or "").upper(): item
            for item in watch_items if item.get("symbol")
        }

        positions = [self._compact_position(item) for item in positions_raw]
        latest_quant_data = latest_quant.load() or {}
        quant_candidates = latest_quant.candidates()
        quant_by_symbol = {
            item.get("symbol"): item
            for item in quant_candidates if item.get("symbol")
        }
        quant_symbols = set(quant_by_symbol.keys())

        terminal_states = {
            "FILLED_ALL", "CANCELLED_ALL", "CANCELED_ALL", "FAILED", "DELETED",
        }
        pending_orders = [
            self._compact_order(item)
            for item in orders_raw
            if str(item.get("status", "")).upper() not in terminal_states
        ]

        symbols = []

        def add_symbol(symbol):
            symbol = str(symbol or "").upper()
            if symbol.startswith("US.") and symbol not in symbols:
                symbols.append(symbol)

        for item in positions_raw:
            add_symbol(item.get("symbol"))
        for item in pending_orders:
            add_symbol(item.get("symbol"))
        for item in quant_candidates:
            add_symbol(item.get("symbol"))

        base_candidate_count = len(symbols)

        # Monitored Securities are persistent operator/AI monitoring intent, so
        # they are not silently dropped merely because the quant list filled the
        # soft candidate target. The target remains informational/soft; held,
        # pending, quant and enabled watchlist names may legitimately exceed it.
        for item in watch_items:
            add_symbol(item.get("symbol"))

        held_symbols = {str(item.get("symbol") or "").upper() for item in positions_raw if item.get("symbol")}
        watch_symbols = set(watch_by_symbol.keys())
        pending_symbols = {str(item.get("symbol") or "").upper() for item in pending_orders if item.get("symbol")}

        # Held names, quant candidates and all enabled monitored securities are
        # research-eligible. One OpenD snapshot request supplies fresh market
        # data before clustered research and final portfolio reasoning.
        research_symbols = [
            symbol for symbol in symbols
            if symbol in held_symbols or symbol in quant_symbols or symbol in watch_symbols
        ]
        snapshots_by_symbol = self._market_snapshots(research_symbols)

        research_requests = []
        if enrich_research:
            for symbol in research_symbols:
                quant_item = quant_by_symbol.get(symbol) or {}
                metrics = quant_item.get("metrics") or {}
                company_name = quant_item.get("name")
                if not company_name:
                    position_item = next(
                        (item for item in positions_raw if str(item.get("symbol") or "").upper() == symbol),
                        None,
                    )
                    if position_item:
                        company_name = position_item.get("name")
                if not company_name:
                    company_name = (watch_by_symbol.get(symbol) or {}).get("name")

                relationships = []
                if symbol in held_symbols:
                    relationships.append("HELD")
                if symbol in watch_symbols:
                    relationships.append("WATCHLIST")
                if symbol in quant_symbols:
                    relationships.append("QUANT_CANDIDATE")
                if symbol in pending_symbols:
                    relationships.append("PENDING_ORDER")

                quant_research_context = None
                if quant_item:
                    quant_research_context = {
                        "rank": quant_item.get("rank"),
                        "scores": quant_item.get("quant"),
                        "metrics": metrics,
                        "discovery_sources": quant_item.get("sources"),
                    }

                research_requests.append({
                    "symbol": symbol,
                    "company_name": company_name,
                    "relationships": relationships,
                    "market_snapshot": snapshots_by_symbol.get(symbol),
                    "quant_context": quant_research_context,
                })

        research_by_symbol = ai_research_batches.research_many(
            research_requests,
            progress_callback=research_progress_callback,
        ) if research_requests else {}

        candidates = []
        for symbol in symbols:
            if symbol in held_symbols and symbol in watch_symbols:
                relationship = "HELD_AND_WATCHLIST"
            elif symbol in held_symbols:
                relationship = "HELD"
            elif symbol in pending_symbols:
                relationship = "PENDING_ORDER"
            elif symbol in quant_symbols and symbol in watch_symbols:
                relationship = "QUANT_AND_WATCHLIST"
            elif symbol in quant_symbols:
                relationship = "QUANT_CANDIDATE"
            else:
                relationship = "WATCHLIST"

            memory = ai_context.build_memory_context(
                symbol=symbol,
                decision_limit=decision_limit,
                rejection_limit=rejection_limit,
            )

            quant_item = quant_by_symbol.get(symbol)
            quant_context = None
            event_review = None
            if quant_item:
                metrics = quant_item.get("metrics") or {}
                quant_context = {
                    "rank": quant_item.get("rank"),
                    "scores": quant_item.get("quant"),
                    "metrics": metrics,
                    "discovery_sources": quant_item.get("sources"),
                }
                requires_review = bool(
                    metrics.get("requires_event_review") or metrics.get("discontinuity_flag")
                )
                event_review = {
                    "required": requires_review,
                    "status": "PENDING_AI_REVIEW" if requires_review else "NOT_REQUIRED",
                    "reason": "EXTREME_PRICE_MOVE" if requires_review else None,
                    "events": metrics.get("discontinuity_events") or [],
                }

            relationships = []
            if symbol in held_symbols:
                relationships.append("HELD")
            if symbol in watch_symbols:
                relationships.append("WATCHLIST")
            if symbol in quant_symbols:
                relationships.append("QUANT_CANDIDATE")
            if symbol in pending_symbols:
                relationships.append("PENDING_ORDER")

            candidates.append({
                "symbol": symbol,
                "relationship": relationship,
                "relationships": relationships,
                "market_snapshot": snapshots_by_symbol.get(symbol),
                "quant": quant_context,
                "research_context": research_by_symbol.get(symbol),
                "event_review": event_review,
                "account_sizing_snapshot": (quant_item or {}).get("account_sizing"),
                "watchlist": watch_by_symbol.get(symbol) or memory.get("watchlist"),
                "active_thesis": memory.get("active_thesis"),
                "recent_decisions": memory.get("recent_decisions"),
                "rejection_summary": memory.get("rejection_summary"),
            })

        return {
            "schema_version": 5,
            "run": {
                "type": run_type.upper(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scope": "US",
                "candidate_count": len(candidates),
                "soft_candidate_target": int(max_candidates),
                "base_candidate_count": base_candidate_count,
                "watchlist_candidate_count": len(watch_symbols),
                "research_enabled": bool(enrich_research),
                "research_request_count": len(research_requests),
                "research_parallel_batches": (
                    ai_research_batches.parallel_batches if enrich_research else 0
                ),
            },
            "market_context": self._market_context(),
            "deterministic_risk_policy": self._risk_policy(),
            "portfolio": {
                "account": {
                    "mode": account.get("mode"),
                    "total_value": account.get("total_value"),
                    "cash": account.get("cash"),
                    "market_value": account.get("market_value"),
                },
                "positions": positions,
                "pending_orders": pending_orders,
            },
            "quant_context": {
                "account_context_at_scan": (latest_quant_data.get("result") or latest_quant_data).get("account_context"),
                "account_sizing_note": "Scan annotations are historical. Use the current portfolio account available_cash for decisions; execution revalidates funds.",
                "run_id": latest_quant_data.get("run_id"),
                "generated_at": latest_quant_data.get("generated_at"),
                "candidate_count": len(quant_candidates),
            },
            "candidates": candidates,
        }


ai_run_context = AIRunContextBuilder()
