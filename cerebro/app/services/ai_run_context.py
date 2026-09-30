from datetime import datetime, timezone

from app.services.ai_context import ai_context
from app.services.opend import opend
from app.services.trading import trading
from app.services.watchlist import watchlist
from app.services.latest_quant import (
    latest_quant
)
from app.services.ai_web_research import (
    ai_web_research
)


class AIRunContextBuilder:

    def _compact_position(self, item):
        """
        Keep only fields useful to the model.
        Unknown/missing fields are harmless.
        """

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

        #
        # Normalize whatever shape OpenDClient returns.
        #
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
                    {
                        "market": key,
                        "state": value
                    }
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

        #
        # Preserve raw US state if found.
        #
        return {
            "market": "US",
            "timezone": "America/New_York",
            "state": us,
        }

    def build(
        self,
        *,
        run_type="MANUAL",
        max_candidates=30
    ):
        #
        # IMPORTANT:
        # These broker calls happen ONCE for the
        # entire AI run, not once per security.
        #
        account = trading.get_account_summary()
        positions_raw = trading.get_positions()
        orders_raw = trading.get_orders()

        watch_items = [
            item
            for item in watchlist.list()
            if item.get("enabled", True)
            and str(
                item.get("market") or ""
            ).upper() in {"", "US"}
            and str(
                item.get("symbol", "")
            ).upper().startswith("US.")
        ]

        positions = [
            self._compact_position(item)
            for item in positions_raw
        ]

        #
        # Latest successful quant Top N.
        #
        latest_quant_data = (
            latest_quant.load()
            or {}
        )

        quant_candidates = (
            latest_quant.candidates()
        )

        quant_by_symbol = {
            item.get("symbol"):
                item
            for item in quant_candidates
            if item.get("symbol")
        }

        quant_symbols = set(
            quant_by_symbol.keys()
        )

        pending_orders = []

        terminal_states = {
            "FILLED_ALL",
            "CANCELLED_ALL",
            "CANCELED_ALL",
            "FAILED",
            "DELETED",
        }

        for item in orders_raw:
            status = str(
                item.get("status", "")
            ).upper()

            if status not in terminal_states:
                pending_orders.append(
                    self._compact_order(item)
                )

        #
        # Build decision universe.
        #
        # Mandatory:
        #   1. current US holdings
        #   2. pending US orders
        #   3. all latest quant candidates
        #
        # Watchlist names only fill spare capacity.
        #
        symbols = []

        def add_symbol(symbol):
            if (
                symbol
                and str(symbol).startswith("US.")
                and symbol not in symbols
            ):
                symbols.append(symbol)

        for item in positions_raw:
            add_symbol(
                item.get("symbol")
            )

        for item in pending_orders:
            add_symbol(
                item.get("symbol")
            )

        for item in quant_candidates:
            add_symbol(
                item.get("symbol")
            )

        mandatory_count = len(symbols)

        optional_slots = max(
            0,
            max_candidates - mandatory_count
        )

        optional_watch_symbols = []

        for item in watch_items:
            symbol = item.get("symbol")

            if (
                symbol
                and symbol not in symbols
                and symbol not in optional_watch_symbols
            ):
                optional_watch_symbols.append(
                    symbol
                )

        symbols.extend(
            optional_watch_symbols[
                :optional_slots
            ]
        )

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

        #
        # AI web research is performed for:
        #
        #   1. current portfolio holdings
        #   2. latest quant candidates
        #
        # Research is cached, so repeated AI context
        # builds do not repeatedly consume API calls.
        #
        research_requests = []

        for symbol in symbols:

            if (
                symbol not in held_symbols
                and symbol not in quant_symbols
            ):
                continue

            quant_item = (
                quant_by_symbol.get(
                    symbol
                )
                or {}
            )

            metrics = (
                quant_item.get(
                    "metrics"
                )
                or {}
            )

            company_name = (
                quant_item.get(
                    "name"
                )
            )

            if not company_name:
                position_item = next(
                    (
                        item
                        for item
                        in positions_raw
                        if item.get(
                            "symbol"
                        ) == symbol
                    ),
                    None
                )

                if position_item:
                    company_name = (
                        position_item.get(
                            "name"
                        )
                    )

            relationships = []

            if symbol in held_symbols:
                relationships.append(
                    "HELD"
                )

            if symbol in watch_symbols:
                relationships.append(
                    "WATCHLIST"
                )

            if symbol in quant_symbols:
                relationships.append(
                    "QUANT_CANDIDATE"
                )

            if any(
                order.get(
                    "symbol"
                ) == symbol
                for order
                in pending_orders
            ):
                relationships.append(
                    "PENDING_ORDER"
                )

            quant_research_context = None

            if quant_item:
                quant_research_context = {
                    "rank":
                        quant_item.get(
                            "rank"
                        ),

                    "scores":
                        quant_item.get(
                            "quant"
                        ),

                    "metrics":
                        metrics,

                    "discovery_sources":
                        quant_item.get(
                            "sources"
                        ),
                }

            research_requests.append({
                "symbol":
                    symbol,

                "company_name":
                    company_name,

                "relationships":
                    relationships,

                "quant_context":
                    quant_research_context,
            })

        research_by_symbol = (
            ai_web_research
            .research_many(
                research_requests
            )
        )

        candidates = []

        for symbol in symbols:

            if (
                symbol in held_symbols
                and symbol in watch_symbols
            ):
                relationship = (
                    "HELD_AND_WATCHLIST"
                )

            elif symbol in held_symbols:
                relationship = "HELD"

            elif any(
                order.get("symbol") == symbol
                for order in pending_orders
            ):
                relationship = "PENDING_ORDER"

            elif symbol in quant_symbols:
                relationship = "QUANT_CANDIDATE"

            else:
                relationship = "WATCHLIST"

            memory = (
                ai_context
                .build_memory_context(
                    symbol=symbol,
                    decision_limit=5,
                    rejection_limit=5
                )
            )

            quant_item = (
                quant_by_symbol.get(
                    symbol
                )
            )

            quant_context = None
            event_review = None

            if quant_item:
                metrics = (
                    quant_item.get(
                        "metrics"
                    )
                    or {}
                )

                quant_context = {
                    "rank":
                        quant_item.get(
                            "rank"
                        ),

                    "scores":
                        quant_item.get(
                            "quant"
                        ),

                    "metrics":
                        metrics,

                    "discovery_sources":
                        quant_item.get(
                            "sources"
                        ),
                }

                requires_review = bool(
                    metrics.get(
                        "requires_event_review"
                    )
                    or metrics.get(
                        "discontinuity_flag"
                    )
                )

                event_review = {
                    "required":
                        requires_review,

                    "status":
                        (
                            "PENDING_AI_REVIEW"
                            if requires_review
                            else "NOT_REQUIRED"
                        ),

                    "reason":
                        (
                            "EXTREME_PRICE_MOVE"
                            if requires_review
                            else None
                        ),

                    "events":
                        (
                            metrics.get(
                                "discontinuity_events"
                            )
                            or []
                        ),
                }

            relationships = []

            if symbol in held_symbols:
                relationships.append(
                    "HELD"
                )

            if symbol in watch_symbols:
                relationships.append(
                    "WATCHLIST"
                )

            if symbol in quant_symbols:
                relationships.append(
                    "QUANT_CANDIDATE"
                )

            if any(
                order.get(
                    "symbol"
                ) == symbol
                for order
                in pending_orders
            ):
                relationships.append(
                    "PENDING_ORDER"
                )

            candidates.append({
                "symbol": symbol,

                "relationship":
                    relationship,

                "relationships":
                    relationships,

                "quant":
                    quant_context,

                "research_context":
                    research_by_symbol.get(
                        symbol
                    ),

                "event_review":
                    event_review,

                #
                # Deliberately no portfolio here.
                #
                "watchlist":
                    memory.get(
                        "watchlist"
                    ),

                "active_thesis":
                    memory.get(
                        "active_thesis"
                    ),

                "recent_decisions":
                    memory.get(
                        "recent_decisions"
                    ),

                "rejection_summary":
                    memory.get(
                        "rejection_summary"
                    ),
            })

        return {
            "schema_version": 1,

            "run": {
                "type":
                    run_type.upper(),

                "generated_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat(),

                "scope": "US",

                "candidate_count":
                    len(candidates),

                "mandatory_candidate_count":
                    mandatory_count,

                "optional_watchlist_count":
                    max(
                        0,
                        len(candidates)
                        - mandatory_count
                    ),
            },

            "market_context":
                self._market_context(),

            "portfolio": {
                "account": {
                    "mode":
                        account.get("mode"),

                    "total_value":
                        account.get(
                            "total_value"
                        ),

                    "cash":
                        account.get("cash"),

                    "market_value":
                        account.get(
                            "market_value"
                        ),
                },

                "positions":
                    positions,

                "pending_orders":
                    pending_orders,
            },

            "quant_context": {
                "run_id":
                    latest_quant_data.get(
                        "run_id"
                    ),

                "generated_at":
                    latest_quant_data.get(
                        "generated_at"
                    ),

                "candidate_count":
                    len(
                        quant_candidates
                    ),
            },

            "candidates":
                candidates,
        }


ai_run_context = AIRunContextBuilder()
