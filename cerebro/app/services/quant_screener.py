from statistics import mean

from moomoo import (
    OpenQuoteContext,
    Market,
    SimpleFilter,
    StockField,
    SortDir,
    RET_OK,
)

from app.services.market_metrics import (
    market_metrics
)
from app.services.market_series import market_series
from app.services.universe import universe_service
from app.services.local_discovery import local_discovery
from app.services.opend import opend


class QuantScreener:

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

    def run(
        self,
        *,
        final_limit=25,
        per_screen=40,
        deep_limit=60,
        min_price=5,
        min_market_cap=1_000_000_000,
        progress_callback=None,
    ):
        #
        # Stage 1:
        # refresh authoritative listed universe.
        #
        self._progress(
            progress_callback,
            stage="UNIVERSE_REFRESH",
            processed=0,
            total=2,
            current_symbol=None,
            message="Refreshing Nasdaq Trader universe"
        )

        listing_universe = universe_service.refresh()

        universe_symbols = list(
            listing_universe[
                "eligible"
            ].keys()
        )

        self._progress(
            progress_callback,
            stage="SNAPSHOT_UNIVERSE",
            discovered=len(universe_symbols),
            processed=0,
            total=len(universe_symbols),
            current_symbol=None,
            message=(
                f"Snapshotting "
                f"{len(universe_symbols)} "
                f"eligible securities"
            )
        )

        #
        # Snapshot full eligible universe once.
        #
        (
            snapshot_map,
            snapshot_failures
        ) = self._batched_snapshots(
            universe_symbols + ["US.SPY"]
        )

        #
        # Convert list-style snapshot result
        # into symbol -> snapshot map if needed.
        #
        if isinstance(snapshot_map, list):
            snapshot_map = {
                row["symbol"]: row
                for row in snapshot_map
                if row.get("symbol")
            }

        #
        # Stage 2:
        # fully local snapshot discovery.
        #
        self._progress(
            progress_callback,
            stage="SNAPSHOT_DISCOVERY",
            discovered=len(universe_symbols),
            processed=len(snapshot_map),
            total=len(universe_symbols),
            snapshot_success=len(snapshot_map),
            snapshot_failed=len(snapshot_failures),
            current_symbol=None,
            message="Ranking snapshot universe locally"
        )

        discovery = local_discovery.run(
            snapshot_map,
            per_screen=per_screen,
            final_pool=200,
            min_price=min_price,
            min_market_cap=min_market_cap,
        )

        candidates = discovery[
            "candidates"
        ]

        discovered_before_universe = discovery[
            "discovered_unique"
        ]

        universe_rejected = []

        #
        # Stage 3:
        # only expensive candle analysis
        # for strongest discovered names.
        #
        #
        # Deep-analyse the strongest candidates
        # selected by local snapshot discovery.
        #
        # Snapshot discovery is intentionally cheap.
        # Historical factor analysis remains the
        # expensive second-stage ranking process.
        #
        deep_candidates = candidates

        analysed = []

        #
        # Determine current US state once.
        #
        market_states = (
            opend.get_market_states()
        )

        us_state = None

        for state in market_states:
            if str(
                state.get("id")
                or state.get("market")
                or ""
            ).upper() == "US":
                us_state = state.get(
                    "state"
                )
                break

        cache_hits = 0
        history_fetched = 0
        analysis_failures = 0

        self._progress(
            progress_callback,
            stage="HISTORICAL_ANALYSIS",
            discovered=len(candidates),
            processed=0,
            total=len(deep_candidates),
            snapshot_success=len(
                snapshot_map
            ),
            snapshot_failed=len(
                snapshot_failures
            ),
            cache_hits=0,
            history_fetched=0,
            analysis_success=0,
            analysis_failures=0,
            current_symbol=None,
            message="Starting historical analysis"
        )

        for index, item in enumerate(
            deep_candidates,
            start=1
        ):
            symbol = item["symbol"]

            self._progress(
                progress_callback,
                stage="HISTORICAL_ANALYSIS",
                current_symbol=symbol,
                processed=index - 1,
                total=len(deep_candidates),
                cache_hits=cache_hits,
                history_fetched=history_fetched,
                analysis_success=len(
                    analysed
                ),
                analysis_failures=analysis_failures,
                message=(
                    f"Analysing {symbol}"
                )
            )

            try:
                series = (
                    market_series.build(
                        item["symbol"],
                        snapshot=snapshot_map.get(
                            item["symbol"]
                        ),
                        market_state=us_state,
                        minimum_bars=300
                    )
                )

                sync_info = (
                    series.get(
                        "history_sync",
                        {}
                    )
                )

                if (
                    sync_info.get(
                        "source"
                    )
                    == "CACHE"
                ):
                    cache_hits += 1
                else:
                    history_fetched += 1

                metrics = (
                    market_metrics.build(
                        item["symbol"],
                        candles=series[
                            "bars"
                        ]
                    )
                )

            except Exception as exc:
                analysis_failures += 1
                metrics = {
                    "symbol":
                        item["symbol"],

                    "available":
                        False,

                    "error":
                        str(exc),
                }

            if not metrics.get(
                "available"
            ):
                self._progress(
                    progress_callback,
                    stage="HISTORICAL_ANALYSIS",
                    current_symbol=symbol,
                    processed=index,
                    total=len(
                        deep_candidates
                    ),
                    cache_hits=cache_hits,
                    history_fetched=history_fetched,
                    analysis_success=len(
                        analysed
                    ),
                    analysis_failures=analysis_failures,
                    message=(
                        f"Skipped {symbol}"
                    )
                )

                continue

            analysed.append({
                **item,
                "metrics":
                    metrics
            })

            self._progress(
                progress_callback,
                stage="HISTORICAL_ANALYSIS",
                current_symbol=symbol,
                processed=index,
                total=len(
                    deep_candidates
                ),
                cache_hits=cache_hits,
                history_fetched=history_fetched,
                analysis_success=len(
                    analysed
                ),
                analysis_failures=analysis_failures,
                message=(
                    f"Analysed {index} / "
                    f"{len(deep_candidates)}"
                )
            )

        #
        # Benchmark uses the same
        # cache + live overlay path.
        #
        spy_series = (
            market_series.build(
                "US.SPY",
                snapshot=snapshot_map.get(
                    "US.SPY"
                ),
                market_state=us_state,
                minimum_bars=300
            )
        )

        spy = (
            market_metrics.build(
                "US.SPY",
                candles=spy_series[
                    "bars"
                ]
            )
        )

        #
        # Stage 4:
        # calculate raw factor values.
        #
        for item in analysed:
            metrics = item[
                "metrics"
            ]

            item[
                "_factor_raw"
            ] = {
                "momentum":
                    self._momentum_raw(
                        metrics
                    ),

                "trend":
                    self._trend_raw(
                        metrics
                    ),

                "relative_strength":
                    self._relative_strength_raw(
                        metrics,
                        spy
                    ),

                "breakout":
                    self._breakout_raw(
                        metrics
                    ),

                "volume":
                    self._volume_raw(
                        metrics
                    ),

                "volatility_quality":
                    self._volatility_raw(
                        metrics
                    ),

                "overextension_quality":
                    self._overextension_raw(
                        metrics
                    ),
            }

        #
        # Stage 5:
        # convert raw factor values into
        # cross-sectional percentile scores.
        #
        factor_names = [
            "momentum",
            "trend",
            "relative_strength",
            "breakout",
            "volume",
            "volatility_quality",
            "overextension_quality",
        ]

        for factor in factor_names:

            values = [
                (
                    item["symbol"],
                    item[
                        "_factor_raw"
                    ].get(
                        factor
                    )
                )
                for item in analysed
            ]

            percentiles = (
                self._percentiles(
                    values
                )
            )

            for item in analysed:
                item.setdefault(
                    "quant",
                    {}
                )

                item[
                    "quant"
                ][factor] = (
                    percentiles.get(
                        item["symbol"]
                    )
                )

        #
        # Stage 6:
        # ensemble scoring.
        #
        for item in analysed:

            q = item[
                "quant"
            ]

            composite = (
                self._weighted_score(
                    q
                )
            )

            confidence = (
                self._signal_confidence(
                    q
                )
            )

            item[
                "quant"
            ][
                "composite_score"
            ] = composite

            item[
                "quant"
            ][
                "signal_confidence"
            ] = confidence

            item[
                "quant"
            ][
                "agreement"
            ] = (
                self._agreement(
                    q
                )
            )

            item.pop(
                "_factor_raw",
                None
            )

        analysed.sort(
            key=lambda x:
                x["quant"][
                    "composite_score"
                ],
            reverse=True
        )

        #
        # Final universe percentile.
        #
        total = len(
            analysed
        )

        for index, item in enumerate(
            analysed,
            start=1
        ):
            item[
                "rank"
            ] = index

            if total > 1:
                percentile = (
                    100
                    * (
                        total
                        - index
                    )
                    / (
                        total - 1
                    )
                )
            else:
                percentile = 100

            item[
                "quant"
            ][
                "pool_percentile"
            ] = round(
                percentile,
                2
            )

        final = analysed[
            :final_limit
        ]

        return {
            "market": "US",

            "method":
                "LOCAL_SNAPSHOT_MULTI_FACTOR_V2",

            "screens":
                discovery[
                    "screens"
                ],

            "universe_source":
                listing_universe[
                    "source"
                ],

            "universe_size":
                listing_universe[
                    "eligible_count"
                ],

            "universe_sources":
                listing_universe[
                    "sources"
                ],

            "snapshot_requested":
                len(universe_symbols),

            "snapshot_eligible":
                discovery[
                    "snapshot_eligible"
                ],

            "discovered_unique":
                discovery[
                    "discovered_unique"
                ],

            "discovery_selected":
                discovery[
                    "selected"
                ],

            "snapshot_success":
                len(snapshot_map),

            "snapshot_failed":
                len(snapshot_failures),

            "snapshot_failures":
                snapshot_failures,

            "deep_requested":
                len(deep_candidates),

            "deep_analysed":
                len(analysed),

            "returned":
                len(final),

            "benchmark": {
                "symbol":
                    "US.SPY",

                "return_20d_pct":
                    spy.get(
                        "return_20d_pct"
                    ),

                "return_60d_pct":
                    spy.get(
                        "return_60d_pct"
                    ),

                "return_120d_pct":
                    spy.get(
                        "return_120d_pct"
                    ),
            },

            "candidates":
                final,
        }

    def _progress(
        self,
        callback,
        **values
    ):
        if callback is None:
            return

        try:
            callback(
                **values
            )
        except Exception:
            #
            # Progress reporting must never
            # break a quant run.
            #
            pass


    def _batched_snapshots(
        self,
        symbols,
        batch_size=400
    ):
        """
        Batch snapshots while efficiently isolating
        unsupported quote symbols.

        Moomoo identifies the bad symbol in errors such
        as:

        "US OTC market quote is not available for DCCPY."

        Remove that symbol and retry the remaining batch
        instead of recursively splitting everything.
        """

        import re
        import time

        result = {}
        failures = {}

        symbols = list(
            dict.fromkeys(
                symbol
                for symbol in symbols
                if symbol
            )
        )

        for i in range(
            0,
            len(symbols),
            batch_size
        ):
            remaining = list(
                symbols[
                    i:i + batch_size
                ]
            )

            while remaining:

                try:
                    rows = (
                        opend.get_snapshots(
                            remaining
                        )
                    )

                    for row in rows:
                        symbol = (
                            row.get("symbol")
                            or row.get("code")
                            or row.get(
                                "stock_code"
                            )
                        )

                        if symbol:
                            result[
                                symbol
                            ] = row

                    #
                    # Whole remaining batch succeeded.
                    #
                    break

                except Exception as exc:

                    message = str(exc)

                    #
                    # Historical/snapshot request limits
                    # use rolling windows. If another
                    # Cerebro component consumed quota,
                    # wait for the window to clear.
                    #
                    if (
                        "high frequency"
                        in message.lower()
                    ):
                        time.sleep(31)
                        continue

                    #
                    # Example:
                    #
                    # US OTC market quote is not
                    # available for DCCPY.
                    #
                    match = re.search(
                        r"not available for "
                        r"([A-Za-z0-9.\-]+)",
                        message,
                        re.IGNORECASE
                    )

                    if match:

                        raw_symbol = (
                            match.group(1)
                            .rstrip(".")
                            .upper()
                        )

                        full_symbol = (
                            raw_symbol
                            if raw_symbol.startswith(
                                "US."
                            )
                            else
                            "US." + raw_symbol
                        )

                        failures[
                            full_symbol
                        ] = message

                        remaining = [
                            symbol
                            for symbol
                            in remaining
                            if symbol.upper()
                            != full_symbol
                        ]

                        continue

                    #
                    # Unknown batch error:
                    # don't create hundreds of recursive
                    # requests. Record the batch instead.
                    #
                    for symbol in remaining:
                        failures[
                            symbol
                        ] = message

                    break

        return result, failures


    def _screen(
        self,
        sort_field,
        sort_dir,
        limit,
        min_price,
        min_market_cap
    ):
        ctx = self._ctx()

        try:
            price = SimpleFilter()
            price.stock_field = (
                StockField.CUR_PRICE
            )
            price.filter_min = (
                min_price
            )
            price.is_no_filter = False

            cap = SimpleFilter()
            cap.stock_field = (
                StockField.MARKET_VAL
            )
            cap.filter_min = (
                min_market_cap
            )
            cap.is_no_filter = False

            ranking = (
                SimpleFilter()
            )

            ranking.stock_field = (
                sort_field
            )

            ranking.is_no_filter = True
            ranking.sort = sort_dir

            ret, data = (
                ctx.get_stock_filter(
                    market=Market.US,
                    filter_list=[
                        price,
                        cap,
                        ranking
                    ],
                    begin=0,
                    num=min(
                        limit,
                        200
                    )
                )
            )

            if ret != RET_OK:
                #
                # A single unsupported factor
                # should not kill the whole run.
                #
                return []

            _, _, rows = data

            result = []

            for row in rows:
                result.append({
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
                })

            return [
                x for x in result
                if x.get("symbol")
            ]

        finally:
            ctx.close()

    def _discovery_score(
        self,
        item,
        per_screen
    ):
        score = 0.0

        #
        # Multiple independent models
        # discovering the same security
        # is valuable.
        #
        score += (
            len(
                item["sources"]
            )
            * 20
        )

        for rank in (
            item[
                "source_ranks"
            ].values()
        ):
            score += (
                max(
                    0,
                    per_screen
                    - rank
                    + 1
                )
                / per_screen
                * 10
            )

        return round(
            score,
            3
        )

    def _momentum_raw(
        self,
        m
    ):
        values = []

        weights = {
            "return_10d_pct":
                0.10,

            "return_20d_pct":
                0.25,

            "return_50d_pct":
                0.20,

            "return_60d_pct":
                0.25,

            "return_120d_pct":
                0.20,
        }

        for key, weight in (
            weights.items()
        ):
            value = m.get(
                key
            )

            if value is not None:
                values.append(
                    value
                    * weight
                )

        return (
            sum(values)
            if values
            else None
        )

    def _trend_raw(
        self,
        m
    ):
        score = 0.0

        if m.get(
            "above_ema20"
        ):
            score += 1

        if m.get(
            "above_ema50"
        ):
            score += 1.5

        if m.get(
            "above_ema200"
        ):
            score += 2

        if m.get(
            "ema20_above_50"
        ):
            score += 1.5

        if m.get(
            "ema50_above_200"
        ):
            score += 2

        slope20 = m.get(
            "ema20_slope_pct"
        )

        slope50 = m.get(
            "ema50_slope_pct"
        )

        if slope20 is not None:
            score += (
                slope20
                * 0.5
            )

        if slope50 is not None:
            score += (
                slope50
                * 0.7
            )

        persistence = m.get(
            "pct_above_ema20_20d"
        )

        if persistence is not None:
            score += (
                persistence
                / 100
                * 2
            )

        return score

    def _relative_strength_raw(
        self,
        m,
        spy
    ):
        score = 0.0
        found = False

        for key, weight in [
            (
                "return_20d_pct",
                0.3
            ),
            (
                "return_60d_pct",
                0.4
            ),
            (
                "return_120d_pct",
                0.3
            ),
        ]:
            stock = m.get(
                key
            )

            benchmark = spy.get(
                key
            )

            if (
                stock is not None
                and benchmark
                is not None
            ):
                score += (
                    stock
                    - benchmark
                ) * weight

                found = True

        return (
            score
            if found
            else None
        )

    def _breakout_raw(
        self,
        m
    ):
        position = m.get(
            "range_position_52w"
        )

        high20 = m.get(
            "distance_20d_high_pct"
        )

        high50 = m.get(
            "distance_50d_high_pct"
        )

        score = 0.0
        found = False

        if position is not None:
            score += (
                position
                / 100
                * 3
            )

            found = True

        if high20 is not None:
            #
            # 0 = exactly at high.
            #
            score += (
                max(
                    -10,
                    high20
                )
                + 10
            ) / 10 * 2

            found = True

        if high50 is not None:
            score += (
                max(
                    -15,
                    high50
                )
                + 15
            ) / 15 * 2

            found = True

        return (
            score
            if found
            else None
        )

    def _volume_raw(
        self,
        m
    ):
        v20 = m.get(
            "volume_ratio_20d"
        )

        v50 = m.get(
            "volume_ratio_50d"
        )

        if (
            v20 is None
            and v50 is None
        ):
            return None

        values = [
            v
            for v in [
                v20,
                v50
            ]
            if v is not None
        ]

        #
        # cap extreme spikes so a
        # weird one-day print does not
        # dominate the model.
        #
        values = [
            min(
                v,
                5
            )
            for v in values
        ]

        return mean(
            values
        )

    def _volatility_raw(
        self,
        m
    ):
        atr = m.get(
            "atr_pct"
        )

        vol20 = m.get(
            "realized_vol_20d"
        )

        if (
            atr is None
            and vol20 is None
        ):
            return None

        #
        # We want movement without
        # excessive chaos.
        #
        score = 100.0

        if atr is not None:
            if atr > 10:
                score -= 50

            elif atr > 7:
                score -= 30

            elif atr > 5:
                score -= 15

            elif atr < 1:
                score -= 10

        if vol20 is not None:
            if vol20 > 100:
                score -= 40

            elif vol20 > 70:
                score -= 25

            elif vol20 > 50:
                score -= 10

        return score

    def _overextension_raw(
        self,
        m
    ):
        score = 100.0

        rsi = m.get(
            "rsi_14"
        )

        d20 = m.get(
            "distance_ema20_pct"
        )

        d50 = m.get(
            "distance_ema50_pct"
        )

        if rsi is not None:
            if rsi > 85:
                score -= 45

            elif rsi > 78:
                score -= 25

            elif rsi > 72:
                score -= 10

            elif rsi < 30:
                score -= 20

        if d20 is not None:
            if d20 > 20:
                score -= 35

            elif d20 > 12:
                score -= 20

            elif d20 > 8:
                score -= 10

        if d50 is not None:
            if d50 > 30:
                score -= 20

        return score

    def _percentiles(
        self,
        values
    ):
        clean = [
            (
                symbol,
                value
            )
            for symbol, value
            in values
            if value is not None
        ]

        if not clean:
            return {}

        ordered = sorted(
            clean,
            key=lambda x:
                x[1]
        )

        total = len(
            ordered
        )

        result = {}

        for index, (
            symbol,
            _
        ) in enumerate(
            ordered
        ):
            if total == 1:
                percentile = 100.0

            else:
                percentile = (
                    index
                    / (
                        total - 1
                    )
                    * 100
                )

            result[
                symbol
            ] = round(
                percentile,
                2
            )

        return result

    def _weighted_score(
        self,
        q
    ):
        weights = {
            "momentum":
                0.22,

            "trend":
                0.22,

            "relative_strength":
                0.18,

            "breakout":
                0.12,

            "volume":
                0.10,

            "volatility_quality":
                0.08,

            "overextension_quality":
                0.08,
        }

        total = 0.0
        used = 0.0

        for key, weight in (
            weights.items()
        ):
            value = q.get(
                key
            )

            if value is None:
                continue

            total += (
                value
                * weight
            )

            used += weight

        if used == 0:
            return 0.0

        return round(
            total / used,
            2
        )

    def _agreement(
        self,
        q
    ):
        values = [
            q.get(
                "momentum"
            ),
            q.get(
                "trend"
            ),
            q.get(
                "relative_strength"
            ),
            q.get(
                "breakout"
            ),
            q.get(
                "volume"
            ),
            q.get(
                "volatility_quality"
            ),
            q.get(
                "overextension_quality"
            ),
        ]

        clean = [
            v
            for v in values
            if v is not None
        ]

        if not clean:
            return 0.0

        bullish = [
            v
            for v in clean
            if v >= 60
        ]

        return round(
            len(bullish)
            / len(clean)
            * 100,
            2
        )

    def _signal_confidence(
        self,
        q
    ):
        """
        This is signal confidence,
        NOT a probability of profit.
        """

        factors = [
            value
            for key, value
            in q.items()
            if key in {
                "momentum",
                "trend",
                "relative_strength",
                "breakout",
                "volume",
                "volatility_quality",
                "overextension_quality",
            }
            and value is not None
        ]

        if not factors:
            return 0.0

        average = mean(
            factors
        )

        agreement = (
            len(
                [
                    v
                    for v in factors
                    if v >= 60
                ]
            )
            / len(factors)
            * 100
        )

        confidence = (
            average
            * 0.55
            + agreement
            * 0.45
        )

        return round(
            min(
                100,
                max(
                    0,
                    confidence
                )
            ),
            2
        )

    def _num(
        self,
        value
    ):
        try:
            if value is None:
                return None

            return float(
                value
            )

        except Exception:
            return None


quant_screener = QuantScreener()
