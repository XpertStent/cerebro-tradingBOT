from moomoo import (
    OpenQuoteContext,
    Market,
    SimpleFilter,
    StockField,
    SortDir,
    RET_OK,
)


class USScanner:

    def __init__(
        self,
        host="127.0.0.1",
        port=11111
    ):
        self.host = host
        self.port = port

    def _ctx(self):
        return OpenQuoteContext(
            host=self.host,
            port=self.port
        )

    def scan(
        self,
        *,
        limit=30,
        min_price=5,
        min_market_cap=1_000_000_000
    ):
        """
        First-stage US scanner.

        Moomoo provides:
        - price eligibility
        - market-cap eligibility
        - volume-ratio sorting

        Cerebro performs the deeper scoring later.
        """

        ctx = self._ctx()

        try:
            price_filter = SimpleFilter()
            price_filter.stock_field = (
                StockField.CUR_PRICE
            )
            price_filter.filter_min = (
                min_price
            )
            price_filter.is_no_filter = False

            market_cap_filter = SimpleFilter()
            market_cap_filter.stock_field = (
                StockField.MARKET_VAL
            )
            market_cap_filter.filter_min = (
                min_market_cap
            )
            market_cap_filter.is_no_filter = False

            volume_ratio = SimpleFilter()
            volume_ratio.stock_field = (
                StockField.VOLUME_RATIO
            )

            # Do not filter on ratio yet.
            # Use it only for ranking.
            volume_ratio.is_no_filter = True
            volume_ratio.sort = (
                SortDir.DESCEND
            )

            filters = [
                price_filter,
                market_cap_filter,
                volume_ratio,
            ]

            ret, data = ctx.get_stock_filter(
                market=Market.US,
                filter_list=filters,
                begin=0,
                num=min(
                    limit,
                    200
                )
            )

            if ret != RET_OK:
                raise RuntimeError(
                    str(data)
                )

            (
                last_page,
                all_count,
                rows
            ) = data

            candidates = []

            for rank, row in enumerate(
                rows,
                start=1
            ):
                candidates.append({
                    "rank": rank,

                    "symbol":
                        getattr(
                            row,
                            "stock_code",
                            None
                        ),

                    "name":
                        getattr(
                            row,
                            "stock_name",
                            None
                        ),

                    "price":
                        self._num(
                            getattr(
                                row,
                                "cur_price",
                                None
                            )
                        ),

                    "market_cap":
                        self._num(
                            getattr(
                                row,
                                "market_val",
                                None
                            )
                        ),

                    "volume_ratio":
                        self._num(
                            getattr(
                                row,
                                "volume_ratio",
                                None
                            )
                        ),
                })

            return {
                "market": "US",
                "last_page": bool(
                    last_page
                ),
                "available_count":
                    all_count,
                "returned_count":
                    len(candidates),
                "candidates":
                    candidates
            }

        finally:
            ctx.close()

    def _num(self, value):
        try:
            if value is None:
                return None

            return float(value)

        except Exception:
            return None


scanner = USScanner()
