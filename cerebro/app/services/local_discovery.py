import math


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
        per_screen=60,
        final_pool=200,
        min_price=5.0,
        min_market_cap=1_000_000_000,
    ):
        eligible = []

        for symbol, row in snapshots.items():

            if symbol == "US.SPY":
                continue

            price = self._num(row.get("price"))
            market_cap = self._num(row.get("market_cap"))
            previous_close = self._num(
                row.get("previous_close")
            )

            if price is None or price < min_price:
                continue

            if (
                market_cap is None
                or market_cap < min_market_cap
            ):
                continue

            if row.get("sec_status") != "NORMAL":
                continue

            if row.get("equity_valid") is not True:
                continue

            if row.get("suspension") is True:
                continue

            if (
                previous_close is None
                or previous_close <= 0
            ):
                continue

            item = dict(row)

            item["daily_change_pct"] = (
                (price / previous_close) - 1
            ) * 100.0

            high52 = self._num(
                row.get("highest52weeks_price")
            )

            if high52 and high52 > 0:
                item["distance_52w_high_pct"] = (
                    (price / high52) - 1
                ) * 100.0
                item["near_52w_score"] = (
                    price / high52
                )
            else:
                item["distance_52w_high_pct"] = None
                item["near_52w_score"] = None

            eligible.append(item)

        def rank(key, reverse=True):
            rows = [
                x for x in eligible
                if self._num(x.get(key)) is not None
            ]

            rows.sort(
                key=lambda x: self._num(x.get(key)),
                reverse=reverse
            )

            return rows[:per_screen]

        pools = {
            "daily_momentum":
                rank("daily_change_pct"),

            "volume_surge":
                rank("volume_ratio"),

            "turnover_rate":
                rank("turnover_rate"),

            "liquidity":
                rank("turnover"),

            "near_52w_high":
                rank("near_52w_score"),
        }

        combined = {}

        for source, rows in pools.items():

            for rank_no, row in enumerate(
                rows,
                start=1
            ):
                symbol = row["symbol"]

                record = combined.setdefault(
                    symbol,
                    {
                        "symbol": symbol,
                        "name": row.get("name"),
                        "price": row.get("price"),
                        "market_cap":
                            row.get("market_cap"),

                        "sources": [],
                        "source_ranks": {},

                        "snapshot_signals": {
                            "daily_change_pct":
                                row.get(
                                    "daily_change_pct"
                                ),
                            "volume_ratio":
                                row.get(
                                    "volume_ratio"
                                ),
                            "turnover_rate":
                                row.get(
                                    "turnover_rate"
                                ),
                            "turnover":
                                row.get(
                                    "turnover"
                                ),
                            "distance_52w_high_pct":
                                row.get(
                                    "distance_52w_high_pct"
                                ),
                        },
                    }
                )

                record["sources"].append(source)

                record[
                    "source_ranks"
                ][source] = rank_no

        #
        # Cheap consensus ranking.
        #
        for item in combined.values():

            score = 0.0

            for rank_no in (
                item["source_ranks"].values()
            ):
                score += (
                    per_screen - rank_no + 1
                ) / per_screen

            #
            # Reward independent screens agreeing.
            #
            score += (
                max(
                    0,
                    len(item["sources"]) - 1
                )
                * 0.30
            )

            item["discovery_score"] = round(
                score,
                6
            )

        discovered = list(
            combined.values()
        )

        discovered.sort(
            key=lambda x:
                x["discovery_score"],
            reverse=True
        )

        selected = discovered[:final_pool]

        return {
            "snapshot_eligible":
                len(eligible),

            "screens": {
                name: len(rows)
                for name, rows in pools.items()
            },

            "discovered_unique":
                len(discovered),

            "selected":
                len(selected),

            "candidates":
                selected,
        }


local_discovery = LocalDiscovery()
