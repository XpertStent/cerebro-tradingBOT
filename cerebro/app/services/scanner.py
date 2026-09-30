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
        min_market_cap=1_000_000_000,
        min_volume=500_000
    ):
        """
        Initial US candidate scanner.

        Uses Moomoo server-side filters rather than
        downloading thousands of securities and
        querying them individually.
        """

        ctx = self._ctx()

        try:
            price_filter = SimpleFilter()
            price_filter.stock_field = (
                StockField.CUR_PRICE
            )
            price_filter.filter_min = min_price
            price_filter.is_no_filter = False

            market_cap_filter = SimpleFilter()
            market_cap_filter.stock_field = (
                StockField.MARKET_VAL
            )
            market_cap_filter.filter_min = (
                min_market_cap
            )
            market_cap_filter.is_no_filter = False

            volume_filter = SimpleFilter()
            volume_filter.stock_field = (
                StockField.VOLUME
            )
            volume_filter.filter_min = min_volume
            volume_filter.is_no_filter = False

            #
            # Rank by volume ratio initially.
            # We will enrich/rerank with our own
            # metrics engine afterwards.
            #
            volume_ratio_filter = SimpleFilter()
            volume_ratio_filter.stock_field = (
                StockField.VOLUME_RATIO
            )
            volume_ratio_filter.is_no_filter = True
            volume_ratio_filter.sort = SortDir.DESCEND

            filters = [
                price_filter,
                market_cap_filter,
                volume_filter,
                volume_ratio_filter,
            ]

            ret, data = ctx.get_stock_filter(
                market=Market.US,
                filter_list=filters,
                begin=0,
                num=min(limit, 200)
            )

            if ret != RET_OK:
                raise RuntimeError(str(data))

            last_page, all_count, rows = data

            candidates = []

            for rank, row in enumerate(
                rows,
                start=1
            ):
                candidates.append({
                    "rank": rank,
                    "symbol":
                        row.stock_code,
                    "name":
                        row.stock_name,
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
                    "volume":
                        self._num(
                            getattr(
                                row,
                                "volume",
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
                    "change_pct":
                        self._num(
                            getattr(
                                row,
                                "change_rate",
                                None
                            )
                        ),
                    "turnover_rate":
                        self._num(
                            getattr(
                                row,
                                "turnover_rate",
                                None
                            )
                        ),
                })

            return {
                "market": "US",
                "available_count": all_count,
                "returned_count":
                    len(candidates),
                "candidates": candidates
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
