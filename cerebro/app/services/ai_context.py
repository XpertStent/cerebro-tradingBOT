from collections import Counter

from app.services.ai_memory import ai_memory
from app.services.watchlist import watchlist
from app.services.trading import trading
from app.services.opend import opend


class AIContextBuilder:

    def build_memory_context(
        self,
        symbol: str,
        decision_limit: int = 10,
        rejection_limit: int = 10
    ):
        """
        Build only persistent AI memory for one symbol.

        This deliberately performs no broker, account,
        order, position, or market-state calls.
        """

        symbol = symbol.upper()

        thesis = ai_memory.get_active_thesis(
            symbol
        )

        decisions = ai_memory.list_decisions(
            symbol=symbol,
            limit=decision_limit
        )

        rejections = (
            ai_memory
            .get_recent_rejections(
                symbol=symbol,
                limit=rejection_limit
            )
        )

        watch_item = watchlist.get(
            symbol
        )

        rejection_codes = Counter(
            item["rejection_code"]
            for item in rejections
            if item.get("rejection_code")
        )

        recent_decisions = []

        for item in decisions:
            recent_decisions.append({
                "id":
                    item["id"],

                "created_at":
                    item["created_at"],

                "action":
                    item["action"],

                "strategy":
                    item["strategy"],

                "confidence":
                    item["confidence"],

                "short_reason":
                    item["short_reason"],

                "what_changed":
                    item["what_changed"],

                "thesis_status":
                    item["thesis_status"],

                "execution_status":
                    item["execution_status"],

                "rejection_code":
                    item["rejection_code"],

                "rejection_reason":
                    item["rejection_reason"]
            })

        compact_thesis = None

        if thesis:
            compact_thesis = {
                "id":
                    thesis["id"],

                "strategy":
                    thesis["strategy"],

                "status":
                    thesis["status"],

                "thesis":
                    thesis["thesis"],

                "invalidation":
                    thesis["invalidation"],

                "opened_at":
                    thesis["opened_at"],

                "last_reviewed_at":
                    thesis["last_reviewed_at"]
            }

        compact_watchlist = None

        if watch_item:
            compact_watchlist = {
                "status":
                    watch_item["status"],

                "source":
                    watch_item["source"],

                "score":
                    watch_item["score"],

                "reason":
                    watch_item["reason"],

                "strategy_hint":
                    watch_item["strategy_hint"],

                "enabled":
                    watch_item["enabled"]
            }

        return {
            "symbol":
                symbol,

            "active_thesis":
                compact_thesis,

            "watchlist":
                compact_watchlist,

            "recent_decisions":
                recent_decisions,

            "rejection_summary": {
                "count":
                    len(rejections),

                "codes":
                    dict(
                        rejection_codes
                    )
            }
        }

    def build_symbol_context(
        self,
        symbol: str,
        decision_limit: int = 10,
        rejection_limit: int = 10
    ):
        symbol = symbol.upper()

        thesis = ai_memory.get_active_thesis(
            symbol
        )

        decisions = ai_memory.list_decisions(
            symbol=symbol,
            limit=decision_limit
        )

        rejections = ai_memory.get_recent_rejections(
            symbol=symbol,
            limit=rejection_limit
        )

        watch_item = watchlist.get(
            symbol
        )

        positions = trading.get_positions()
        orders = trading.get_orders()
        account = trading.get_account_summary()

        position = next(
            (
                item
                for item in positions
                if item.get("symbol") == symbol
            ),
            None
        )

        pending_orders = [
            item
            for item in orders
            if (
                item.get("symbol") == symbol
                and str(
                    item.get("status", "")
                ).upper()
                not in {
                    "FILLED_ALL",
                    "CANCELLED_ALL",
                    "FAILED",
                    "DELETED"
                }
            )
        ]

        market_states = opend.get_market_states()

        symbol_market = (
            symbol.split(".", 1)[0]
            if "." in symbol
            else "US"
        )

        market_context = next(
            (
                item
                for item in market_states
                if item.get("market") == symbol_market
            ),
            None
        )

        rejection_codes = Counter(
            item["rejection_code"]
            for item in rejections
            if item.get("rejection_code")
        )

        recent_decisions = []

        for item in decisions:
            recent_decisions.append({
                "id": item["id"],
                "created_at": item["created_at"],
                "action": item["action"],
                "strategy": item["strategy"],
                "confidence": item["confidence"],
                "short_reason": item["short_reason"],
                "what_changed": item["what_changed"],
                "thesis_status": item["thesis_status"],
                "execution_status": item["execution_status"],
                "rejection_code": item["rejection_code"],
                "rejection_reason": item["rejection_reason"]
            })

        compact_thesis = None

        if thesis:
            compact_thesis = {
                "id": thesis["id"],
                "strategy": thesis["strategy"],
                "status": thesis["status"],
                "thesis": thesis["thesis"],
                "invalidation": thesis["invalidation"],
                "opened_at": thesis["opened_at"],
                "last_reviewed_at": thesis["last_reviewed_at"]
            }

        compact_watchlist = None

        if watch_item:
            compact_watchlist = {
                "status": watch_item["status"],
                "source": watch_item["source"],
                "score": watch_item["score"],
                "reason": watch_item["reason"],
                "strategy_hint": watch_item["strategy_hint"],
                "enabled": watch_item["enabled"]
            }

        return {
            "symbol": symbol,

            "active_thesis": compact_thesis,

            "watchlist": compact_watchlist,

            "market": market_context,

            "portfolio": {
                "account": {
                    "mode": account.get("mode"),
                    "total_value": account.get("total_value"),
                    "cash": account.get("cash"),
                    "market_value": account.get("market_value")
                },

                "position": position,

                "pending_orders": pending_orders
            },

            "recent_decisions": recent_decisions,

            "rejection_summary": {
                "count": len(rejections),
                "codes": dict(
                    rejection_codes
                )
            }
        }


ai_context = AIContextBuilder()
