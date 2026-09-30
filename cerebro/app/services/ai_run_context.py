from datetime import datetime, timezone

from app.services.ai_context import ai_context
from app.services.opend import opend
from app.services.trading import trading
from app.services.watchlist import watchlist


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
        # Build candidate universe from:
        #
        # 1. every current holding
        # 2. enabled US watchlist entries
        #
        symbols = []

        for item in positions_raw:
            symbol = item.get("symbol")

            if (
                symbol
                and symbol.startswith("US.")
                and symbol not in symbols
            ):
                symbols.append(symbol)

        for item in watch_items:
            symbol = item.get("symbol")

            if (
                symbol
                and symbol not in symbols
            ):
                symbols.append(symbol)

        #
        # Pending orders are also relevant AI context.
        #
        for item in pending_orders:
            symbol = item.get("symbol")

            if (
                symbol
                and symbol.startswith("US.")
                and symbol not in symbols
            ):
                symbols.append(symbol)

        symbols = symbols[
            :max_candidates
        ]

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

            else:
                relationship = "WATCHLIST"

            memory = (
                ai_context
                .build_symbol_context(
                    symbol=symbol,
                    decision_limit=5,
                    rejection_limit=5
                )
            )

            candidates.append({
                "symbol": symbol,

                "relationship":
                    relationship,

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

            "candidates":
                candidates,
        }


ai_run_context = AIRunContextBuilder()
