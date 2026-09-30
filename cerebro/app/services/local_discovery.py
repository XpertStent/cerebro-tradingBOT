import math

from app.services.settings import settings


class LocalDiscovery:

    @staticmethod
    def _num(value):
        try:
            value = float(value)
            return None if math.isnan(value) else value
        except Exception:
            return None

    def run(
        self,
        snapshots,
        *,
        per_screen=None,
        screen_limits=None,
        final_pool=None,
        min_price=None,
        min_market_cap=None,
        consensus_bonus=None,
        excluded_symbols=None,
    ):
        """Run independent snapshot screens, then union by consensus.

        Each discovery screen has its own Top-N. ``per_screen`` survives only
        as a compatibility override for callers that intentionally want one
        common limit across every screen.
        """

        default_screen = int(per_screen) if per_screen is not None else None
        configured_limits = {
            "daily_momentum": int(settings.get("discovery.daily_momentum.top_n")),
            "volume_surge": int(settings.get("discovery.volume_surge.top_n")),
            "turnover_rate": int(settings.get("discovery.turnover_rate.top_n")),
            "liquidity": int(settings.get("discovery.liquidity.top_n")),
            "near_52w_high": int(settings.get("discovery.near_52w_high.top_n")),
        }

        if default_screen is not None:
            configured_limits = {
                key: default_screen
                for key in configured_limits
            }

        if screen_limits:
            for key, value in screen_limits.items():
                if key in configured_limits and value is not None:
                    configured_limits[key] = max(1, int(value))

        enabled = {
            "daily_momentum": settings.get_bool("discovery.daily_momentum.enabled"),
            "volume_surge": settings.get_bool("discovery.volume_surge.enabled"),
            "turnover_rate": settings.get_bool("discovery.turnover_rate.enabled"),
            "liquidity": settings.get_bool("discovery.liquidity.enabled"),
            "near_52w_high": settings.get_bool("discovery.near_52w_high.enabled"),
        }

        final_pool = int(
            settings.get("discovery.union_pool")
            if final_pool is None
            else final_pool
        )
        min_price = float(
            settings.get("quant.min_price")
            if min_price is None
            else min_price
        )
        min_market_cap = float(
            settings.get("quant.min_market_cap")
            if min_market_cap is None
            else min_market_cap
        )
        consensus_bonus = float(
            settings.get("discovery.consensus_bonus")
            if consensus_bonus is None
            else consensus_bonus
        )

        excluded = {"US.SPY"}
        excluded.update(
            str(symbol).upper()
            for symbol in (excluded_symbols or [])
            if symbol
        )

        eligible = []

        for symbol, row in snapshots.items():
            if str(symbol).upper() in excluded:
                continue

            price = self._num(row.get("price"))
            market_cap = self._num(row.get("market_cap"))
            previous_close = self._num(row.get("previous_close"))

            if price is None or price < min_price:
                continue
            if market_cap is None or market_cap < min_market_cap:
                continue
            if row.get("sec_status") != "NORMAL":
                continue
            if row.get("equity_valid") is not True:
                continue
            if row.get("suspension") is True:
                continue
            if previous_close is None or previous_close <= 0:
                continue

            item = dict(row)
            item["daily_change_pct"] = ((price / previous_close) - 1) * 100.0

            high52 = self._num(row.get("highest52weeks_price"))
            if high52 and high52 > 0:
                item["distance_52w_high_pct"] = ((price / high52) - 1) * 100.0
                item["near_52w_score"] = price / high52
            else:
                item["distance_52w_high_pct"] = None
                item["near_52w_score"] = None

            eligible.append(item)

        def rank(key, screen_name, reverse=True):
            if not enabled[screen_name]:
                return []

            rows = [
                item
                for item in eligible
                if self._num(item.get(key)) is not None
            ]
            rows.sort(
                key=lambda item: self._num(item.get(key)),
                reverse=reverse,
            )
            return rows[:configured_limits[screen_name]]

        pools = {
            "daily_momentum": rank("daily_change_pct", "daily_momentum"),
            "volume_surge": rank("volume_ratio", "volume_surge"),
            "turnover_rate": rank("turnover_rate", "turnover_rate"),
            "liquidity": rank("turnover", "liquidity"),
            "near_52w_high": rank("near_52w_score", "near_52w_high"),
        }

        combined = {}

        for source, rows in pools.items():
            limit = configured_limits[source]

            for rank_no, row in enumerate(rows, start=1):
                symbol = row["symbol"]
                record = combined.setdefault(
                    symbol,
                    {
                        "symbol": symbol,
                        "name": row.get("name"),
                        "price": row.get("price"),
                        "market_cap": row.get("market_cap"),
                        "sources": [],
                        "source_ranks": {},
                        "snapshot_signals": {
                            "daily_change_pct": row.get("daily_change_pct"),
                            "volume_ratio": row.get("volume_ratio"),
                            "turnover_rate": row.get("turnover_rate"),
                            "turnover": row.get("turnover"),
                            "distance_52w_high_pct": row.get("distance_52w_high_pct"),
                        },
                    },
                )

                record["sources"].append(source)
                record["source_ranks"][source] = rank_no
                record.setdefault("source_limits", {})[source] = limit

        for item in combined.values():
            score = 0.0

            for source, rank_no in item["source_ranks"].items():
                limit = max(1, int(item["source_limits"][source]))
                score += (limit - rank_no + 1) / limit

            score += max(0, len(item["sources"]) - 1) * consensus_bonus
            item["discovery_score"] = round(score, 6)
            item.pop("source_limits", None)

        discovered = list(combined.values())
        discovered.sort(
            key=lambda item: item["discovery_score"],
            reverse=True,
        )

        selected = discovered[:final_pool]

        return {
            "snapshot_eligible": len(eligible),
            "screens": {
                name: {
                    "enabled": enabled[name],
                    "top_n": configured_limits[name],
                    "returned": len(rows),
                }
                for name, rows in pools.items()
            },
            "discovered_unique": len(discovered),
            "selected": len(selected),
            "candidates": selected,
        }


local_discovery = LocalDiscovery()
