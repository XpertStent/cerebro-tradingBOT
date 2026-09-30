from datetime import datetime, timezone

from app.services.ai_context import ai_context
from app.services.opend import opend
from app.services.trading import trading
from app.services.watchlist import watchlist
from app.services.latest_quant import latest_quant
from app.services.ai_web_research import ai_web_research
from app.services.settings import settings


class AIRunContextBuilder:

    def _compact_position(self, item):
        keys = [
            "symbol",
            "name",
            "quantity",
            "qty",
            "available_qty",
            "average_cost",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        ]
        return {
            key: item.get(key)
            for key in keys
            if item.get(key) is not None
        }

    def _compact_order(self, item):
        keys = [
            "order_id",
            "symbol",
            "side",
            "quantity",
            "qty",
            "order_type",
            "price",
            "status",
            "filled_qty",
        ]
        return {
            key: item.get(key)
            for key in keys
            if item.get(key) is not None
        }

    def _market_context(self):
        raw = opend.get_market_states()

        if isinstance(raw, list):
            states = raw
        elif isinstance(raw, dict):
            states = (
                raw.get("markets")
                or raw.get("states")
                or raw.get("market_states")
                or raw.get("data")
                or []
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
                item.get("market")
                or item.get("id")
                or item.get("code")
                or item.get("name")
                or ""
            ).upper()
            if market == "US":
                us = item
                break

        return {
            "market": "US",
            "timezone": "America/New_York",
            "state": us,
        }

    def build(
        self,
        *,
        run_type="MANUAL",
        max_candidates=None,
        enrich_research=None,
    ):
        """Build deterministic decision context.

        Holdings, pending orders and the complete latest quant set are always
        mandatory. Watchlist symbols only fill spare capacity. Expensive web
        research can be disabled for structural validation or inspection.
        """

        if max_candidates is None:
            max_candidates = int(settings.get("ai.context.max_candidates"))

        if enrich_research is None:
            enrich_research = settings.get_bool("ai.research.enabled")

        decision_limit = int(
            settings.get("ai.context.recent_decisions_per_symbol")
        )
        rejection_limit = int(
            settings.get("ai.context.recent_rejections_per_symbol")
        )
        include_watchlist = settings.get_bool("ai.context.include_watchlist")

        # Broker calls happen once per AI run, not once per symbol.
        account = trading.get_account_summary()
        positions_raw = trading.get_positions()
        orders_raw = trading.get_orders()

        watch_items = []
        if include_watchlist:
            watch_items = [
                item
                for item in watchlist.list()
                if item.get("enabled", True)
                and str(item.get("market") or "").upper() in {"", "US"}
                and str(item.get("symbol", "")).upper().startswith("US.")
            ]

        positions = [
            self._compact_position(item)
            for item in positions_raw
        ]

        latest_quant_data = latest_quant.load() or {}
        quant_candidates = latest_quant.candidates()
        quant_by_symbol = {
            item.get("symbol"): item
            for item in quant_candidates
            if item.get("symbol")
        }
        quant_symbols = set(quant_by_symbol.keys())

        terminal_states = {
            "FILLED_ALL",
            "CANCELLED_ALL",
            "CANCELED_ALL",
            "FAILED",
            "DELETED",
        }

        pending_orders = [
            self._compact_order(item)
            for item in orders_raw
            if str(item.get("status", "")).upper() not in terminal_states
        ]

        symbols = []

        def add_symbol(symbol):
            if (
                symbol
                and str(symbol).startswith("US.")
                and symbol not in symbols
            ):
                symbols.append(symbol)

        for item in positions_raw:
            add_symbol(item.get("symbol"))

        for item in pending_orders:
            add_symbol(item.get("symbol"))

        for item in quant_candidates:
            add_symbol(item.get("symbol"))

        mandatory_count = len(symbols)
        optional_slots = max(0, int(max_candidates) - mandatory_count)

        optional_watch_symbols = []
        for item in watch_items:
            symbol = item.get("symbol")
            if (
                symbol
                and symbol not in symbols
                and symbol not in optional_watch_symbols
            ):
                optional_watch_symbols.append(symbol)

        symbols.extend(optional_watch_symbols[:optional_slots])

        held_symbols = {
            item.get("symbol")
            for item in positions_raw
            if item.get("symbol")
        }
        watch_symbols = {
            item.get("symbol")
            for item in watch_items
            if item.get("symbol")
        }
        pending_symbols = {
            item.get("symbol")
            for item in pending_orders
            if item.get("symbol")
        }

        research_requests = []

        if enrich_research:
            for symbol in symbols:
                if symbol not in held_symbols and symbol not in quant_symbols:
                    continue

                quant_item = quant_by_symbol.get(symbol) or {}
                metrics = quant_item.get("metrics") or {}
                company_name = quant_item.get("name")

                if not company_name:
                    position_item = next(
                        (
                            item
                            for item in positions_raw
                            if item.get("symbol") == symbol
                        ),
                        None,
                    )
                    if position_item:
                        company_name = position_item.get("name")

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
                    "quant_context": quant_research_context,
                })

        research_by_symbol = (
            ai_web_research.research_many(research_requests)
            if research_requests
            else {}
        )

        candidates = []

        for symbol in symbols:
            if symbol in held_symbols and symbol in watch_symbols:
                relationship = "HELD_AND_WATCHLIST"
            elif symbol in held_symbols:
                relationship = "HELD"
            elif symbol in pending_symbols:
                relationship = "PENDING_ORDER"
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
                    metrics.get("requires_event_review")
                    or metrics.get("discontinuity_flag")
                )

                event_review = {
                    "required": requires_review,
                    "status": (
                        "PENDING_AI_REVIEW"
                        if requires_review
                        else "NOT_REQUIRED"
                    ),
                    "reason": (
                        "EXTREME_PRICE_MOVE"
                        if requires_review
                        else None
                    ),
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
                "quant": quant_context,
                "research_context": research_by_symbol.get(symbol),
                "event_review": event_review,
                "watchlist": memory.get("watchlist"),
                "active_thesis": memory.get("active_thesis"),
                "recent_decisions": memory.get("recent_decisions"),
                "rejection_summary": memory.get("rejection_summary"),
            })

        return {
            "schema_version": 2,
            "run": {
                "type": run_type.upper(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scope": "US",
                "candidate_count": len(candidates),
                "mandatory_candidate_count": mandatory_count,
                "optional_watchlist_count": max(
                    0,
                    len(candidates) - mandatory_count,
                ),
                "research_enabled": bool(enrich_research),
                "research_request_count": len(research_requests),
            },
            "market_context": self._market_context(),
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
                "run_id": latest_quant_data.get("run_id"),
                "generated_at": latest_quant_data.get("generated_at"),
                "candidate_count": len(quant_candidates),
            },
            "candidates": candidates,
        }


ai_run_context = AIRunContextBuilder()
