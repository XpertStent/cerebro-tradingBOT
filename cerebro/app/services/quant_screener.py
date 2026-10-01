from statistics import mean
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.account_fields import account_context, number
from app.services.trading import trading
from app.services.risk import risk
from app.services.market_metrics import market_metrics
from app.services.market_series import market_series
from app.services.universe import universe_service
from app.services.local_discovery import local_discovery
from app.services.opend import opend
from app.services.settings import settings


class QuantScreener:

    def run(
        self,
        *,
        final_limit=None,
        per_screen=None,
        deep_limit=None,
        min_price=None,
        min_market_cap=None,
        min_current_turnover=None,
        min_median_turnover=None,
        progress_callback=None,
    ):
        """Run snapshot discovery followed by historical multi-factor ranking.

        Explicit arguments remain supported for API/test overrides. When an
        argument is omitted, the persistent Settings registry is authoritative.
        """

        final_limit = int(
            settings.get("quant.final_limit")
            if final_limit is None
            else final_limit
        )
        deep_limit = int(
            settings.get("quant.deep_limit")
            if deep_limit is None
            else deep_limit
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
        min_current_turnover = float(
            settings.get("quant.min_current_turnover")
            if min_current_turnover is None
            else min_current_turnover
        )
        min_median_turnover = float(
            settings.get("quant.min_median_turnover")
            if min_median_turnover is None
            else min_median_turnover
        )

        benchmark_symbol = str(
            settings.get("quant.benchmark_symbol")
            or "US.SPY"
        ).upper()
        snapshot_batch_size = int(
            settings.get("quant.snapshot_batch_size")
        )
        retry_seconds = int(
            settings.get("quant.rate_limit_retry_seconds")
        )
        minimum_history_bars = int(
            settings.get("history.minimum_completed_bars")
        )
        union_pool = int(
            settings.get("discovery.union_pool")
        )

        self._progress(
            progress_callback,
            stage="UNIVERSE_REFRESH",
            processed=0,
            total=2,
            current_symbol=None,
            message="Refreshing Nasdaq Trader universe",
        )

        listing_universe = universe_service.refresh()
        universe_symbols = list(listing_universe["eligible"].keys())

        self._progress(
            progress_callback,
            stage="SNAPSHOT_UNIVERSE",
            discovered=len(universe_symbols),
            processed=0,
            total=len(universe_symbols),
            current_symbol=None,
            message=f"Snapshotting {len(universe_symbols)} eligible securities",
        )

        snapshot_map, snapshot_failures = self._batched_snapshots(
            universe_symbols + [benchmark_symbol],
            batch_size=snapshot_batch_size,
            retry_seconds=retry_seconds,
        )

        if isinstance(snapshot_map, list):
            snapshot_map = {
                row["symbol"]: row
                for row in snapshot_map
                if row.get("symbol")
            }

        self._progress(
            progress_callback,
            stage="SNAPSHOT_DISCOVERY",
            discovered=len(universe_symbols),
            processed=len(snapshot_map),
            total=len(universe_symbols),
            snapshot_success=len(snapshot_map),
            snapshot_failed=len(snapshot_failures),
            current_symbol=None,
            message="Ranking snapshot universe locally",
        )

        discovery = local_discovery.run(
            snapshot_map,
            per_screen=per_screen,
            final_pool=union_pool,
            min_price=min_price,
            min_market_cap=min_market_cap,
        )

        candidates = discovery["candidates"]

        # Deep analysis is intentionally capped. The old implementation
        # accepted deep_limit but then analysed the entire discovery pool.
        deep_candidates = candidates[:deep_limit]

        market_states = opend.get_market_states()
        us_state = None

        for state in market_states:
            if str(state.get("id") or state.get("market") or "").upper() == "US":
                us_state = state.get("state")
                break

        analysed = []
        cache_hits = 0
        history_fetched = 0
        analysis_failures = 0
        analysis_skipped = 0
        analysis_skip_reasons = {}

        self._progress(
            progress_callback,
            stage="HISTORICAL_ANALYSIS",
            discovered=len(candidates),
            processed=0,
            total=len(deep_candidates),
            snapshot_success=len(snapshot_map),
            snapshot_failed=len(snapshot_failures),
            cache_hits=0,
            history_fetched=0,
            analysis_success=0,
            analysis_failures=0,
            current_symbol=None,
            message="Starting historical analysis",
        )

        for index, item in enumerate(deep_candidates, start=1):
            symbol = item["symbol"]

            self._progress(
                progress_callback,
                stage="HISTORICAL_ANALYSIS",
                current_symbol=symbol,
                processed=index - 1,
                total=len(deep_candidates),
                cache_hits=cache_hits,
                history_fetched=history_fetched,
                analysis_success=len(analysed),
                analysis_skipped=analysis_skipped,
                analysis_failures=analysis_failures,
                message=f"Analysing {symbol}",
            )

            snapshot = snapshot_map.get(symbol, {})
            current_turnover = snapshot.get("turnover")

            try:
                current_turnover = float(current_turnover)
            except Exception:
                current_turnover = None

            effective_turnover = current_turnover
            now_ny = datetime.now(ZoneInfo("America/New_York"))
            regular_open = now_ny.replace(
                hour=9, minute=30, second=0, microsecond=0
            )
            regular_close = now_ny.replace(
                hour=16, minute=0, second=0, microsecond=0
            )

            in_regular_session = (
                us_state == "AFTERNOON"
                and regular_open <= now_ny < regular_close
            )

            if in_regular_session and current_turnover is not None:
                elapsed_minutes = max(
                    1.0,
                    (now_ny - regular_open).total_seconds() / 60.0,
                )
                session_fraction = min(1.0, elapsed_minutes / 390.0)
                effective_turnover = current_turnover / session_fraction

            if (
                in_regular_session
                and (
                    effective_turnover is None
                    or effective_turnover < min_current_turnover
                )
            ):
                analysis_skipped += 1
                reason = "LOW_CURRENT_LIQUIDITY"
                analysis_skip_reasons[reason] = analysis_skip_reasons.get(reason, 0) + 1
                self._progress(
                    progress_callback,
                    stage="HISTORICAL_ANALYSIS",
                    current_symbol=symbol,
                    processed=index,
                    total=len(deep_candidates),
                    cache_hits=cache_hits,
                    history_fetched=history_fetched,
                    analysis_success=len(analysed),
                    analysis_skipped=analysis_skipped,
                    analysis_failures=analysis_failures,
                    message=f"Skipped {symbol}: {reason}",
                )
                continue

            try:
                series = market_series.build(
                    symbol,
                    snapshot=snapshot,
                    market_state=us_state,
                    minimum_bars=minimum_history_bars,
                )

                sync_info = series.get("history_sync", {})
                if sync_info.get("source") == "CACHE":
                    cache_hits += 1
                else:
                    history_fetched += 1

                metrics = market_metrics.build(
                    symbol,
                    candles=series["bars"],
                )

            except Exception as exc:
                analysis_failures += 1
                metrics = {
                    "symbol": symbol,
                    "available": False,
                    "error": str(exc),
                }

            if metrics.get("available"):
                median_turnover = metrics.get("median_turnover_60d")
                if (
                    median_turnover is None
                    or median_turnover < min_median_turnover
                ):
                    metrics = {
                        **metrics,
                        "available": False,
                        "skip_reason": "LOW_HISTORICAL_LIQUIDITY",
                    }

            if not metrics.get("available"):
                if not metrics.get("error"):
                    analysis_skipped += 1
                    reason = metrics.get("skip_reason", "UNAVAILABLE_METRICS")
                    analysis_skip_reasons[reason] = analysis_skip_reasons.get(reason, 0) + 1

                self._progress(
                    progress_callback,
                    stage="HISTORICAL_ANALYSIS",
                    current_symbol=symbol,
                    processed=index,
                    total=len(deep_candidates),
                    cache_hits=cache_hits,
                    history_fetched=history_fetched,
                    analysis_success=len(analysed),
                    analysis_skipped=analysis_skipped,
                    analysis_failures=analysis_failures,
                    message=f"Skipped {symbol}",
                )
                continue

            analysed.append({**item, "metrics": metrics})

            self._progress(
                progress_callback,
                stage="HISTORICAL_ANALYSIS",
                current_symbol=symbol,
                processed=index,
                total=len(deep_candidates),
                cache_hits=cache_hits,
                history_fetched=history_fetched,
                analysis_success=len(analysed),
                analysis_skipped=analysis_skipped,
                analysis_failures=analysis_failures,
                message=f"Analysed {index} / {len(deep_candidates)}",
            )

        benchmark_series = market_series.build(
            benchmark_symbol,
            snapshot=snapshot_map.get(benchmark_symbol),
            market_state=us_state,
            minimum_bars=minimum_history_bars,
        )
        benchmark = market_metrics.build(
            benchmark_symbol,
            candles=benchmark_series["bars"],
        )

        for item in analysed:
            metrics = item["metrics"]
            item["_factor_raw"] = {
                "momentum": self._momentum_raw(metrics),
                "trend": self._trend_raw(metrics),
                "relative_strength": self._relative_strength_raw(metrics, benchmark),
                "breakout": self._breakout_raw(metrics),
                "volume": self._volume_raw(metrics),
                "volatility_quality": self._volatility_raw(metrics),
                "overextension_quality": self._overextension_raw(metrics),
            }

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
                (item["symbol"], item["_factor_raw"].get(factor))
                for item in analysed
            ]
            percentiles = self._percentiles(values)

            for item in analysed:
                item.setdefault("quant", {})
                item["quant"][factor] = percentiles.get(item["symbol"])

        for item in analysed:
            q = item["quant"]
            item["quant"]["composite_score"] = self._weighted_score(q)
            item["quant"]["signal_confidence"] = self._signal_confidence(q)
            item["quant"]["agreement"] = self._agreement(q)
            item.pop("_factor_raw", None)

        analysed.sort(
            key=lambda x: x["quant"]["composite_score"],
            reverse=True,
        )

        total = len(analysed)
        for index, item in enumerate(analysed, start=1):
            item["rank"] = index
            percentile = (
                100 * (total - index) / (total - 1)
                if total > 1
                else 100
            )
            item["quant"]["pool_percentile"] = round(percentile, 2)

        final = analysed[:final_limit]
        # Account annotations never alter factor ranks or remove held/watch names.
        # They are a dated sizing snapshot, not execution approval.
        funding = {"status": "UNAVAILABLE"}
        try:
            account = trading.get_account_summary(refresh=True)
            funding = {"status": "CAPTURED", **account_context(account),
                       "captured_at": datetime.now(ZoneInfo("UTC")).isoformat()}
            positions = {p["symbol"]: p for p in trading.get_positions()}
            for item in final:
                symbol = item["symbol"]
                price = number((snapshot_map.get(symbol) or {}).get("price"))
                position = positions.get(symbol) or {}
                available = number(account.get("available_cash"))
                annotation = {"currency": "USD", "reference_price": price,
                              "available_cash": available,
                              "cash_affordable_shares": int(max(0, available) // price) if available is not None and price and price > 0 else None,
                              "execution_context_id": account.get("execution_context_id"),
                              "captured_at": funding["captured_at"]}
                if price and price > 0:
                    preview = risk.evaluate_order(
                        trading_enabled=settings.get_bool("trading.enabled"), mode=trading.mode(),
                        symbol=symbol, side="BUY", quantity=1, estimated_price=price,
                        portfolio_total=account.get("total_value"), portfolio_cash=account.get("cash"),
                        portfolio_available_cash=available, portfolio_market_value=account.get("market_value"),
                        current_position_value=position.get("market_value"), daily_equity_pnl=account.get("daily_pnl"),
                        median_turnover_60d=(item.get("metrics") or {}).get("median_turnover_60d"))
                    annotation["one_share_risk_approved"] = preview["approved"]
                    annotation["risk_checks"] = preview["risk_checks"]
                item["account_sizing"] = annotation
        except Exception as exc:
            funding = {"status": "UNAVAILABLE", "error": str(exc)}
            for item in final:
                item.pop("account_sizing", None)

        return {
            "account_context": funding,
            "market": "US",
            "method": "LOCAL_SNAPSHOT_MULTI_FACTOR_V3",
            "screens": discovery["screens"],
            "universe_source": listing_universe["source"],
            "universe_size": listing_universe["eligible_count"],
            "universe_sources": listing_universe["sources"],
            "snapshot_requested": len(universe_symbols),
            "snapshot_eligible": discovery["snapshot_eligible"],
            "discovered_unique": discovery["discovered_unique"],
            "discovery_selected": discovery["selected"],
            "snapshot_success": len(snapshot_map),
            "snapshot_failed": len(snapshot_failures),
            "snapshot_failures": snapshot_failures,
            "deep_limit": deep_limit,
            "deep_requested": len(deep_candidates),
            "deep_analysed": len(analysed),
            "analysis_skipped": analysis_skipped,
            "analysis_failures": analysis_failures,
            "analysis_skip_reasons": analysis_skip_reasons,
            "liquidity_thresholds": {
                "current_turnover": min_current_turnover,
                "median_turnover_60d": min_median_turnover,
            },
            "returned": len(final),
            "benchmark": {
                "symbol": benchmark_symbol,
                "return_20d_pct": benchmark.get("return_20d_pct"),
                "return_60d_pct": benchmark.get("return_60d_pct"),
                "return_120d_pct": benchmark.get("return_120d_pct"),
            },
            "candidates": final,
        }

    def _progress(self, callback, **values):
        if callback is None:
            return
        try:
            callback(**values)
        except Exception:
            pass

    def _batched_snapshots(
        self,
        symbols,
        batch_size=None,
        retry_seconds=None,
    ):
        import re
        import time

        batch_size = int(
            settings.get("quant.snapshot_batch_size")
            if batch_size is None
            else batch_size
        )
        retry_seconds = int(
            settings.get("quant.rate_limit_retry_seconds")
            if retry_seconds is None
            else retry_seconds
        )

        result = {}
        failures = {}
        symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))

        for i in range(0, len(symbols), batch_size):
            remaining = list(symbols[i:i + batch_size])

            while remaining:
                try:
                    rows = opend.get_snapshots(remaining)
                    for row in rows:
                        symbol = (
                            row.get("symbol")
                            or row.get("code")
                            or row.get("stock_code")
                        )
                        if symbol:
                            result[symbol] = row
                    break

                except Exception as exc:
                    message = str(exc)

                    if "high frequency" in message.lower():
                        time.sleep(retry_seconds)
                        continue

                    match = re.search(
                        r"not available for ([A-Za-z0-9.\-]+)",
                        message,
                        re.IGNORECASE,
                    )

                    if match:
                        raw_symbol = match.group(1).rstrip(".").upper()
                        full_symbol = (
                            raw_symbol
                            if raw_symbol.startswith("US.")
                            else "US." + raw_symbol
                        )
                        failures[full_symbol] = message
                        remaining = [
                            symbol
                            for symbol in remaining
                            if symbol.upper() != full_symbol
                        ]
                        continue

                    for symbol in remaining:
                        failures[symbol] = message
                    break

        return result, failures

    def _momentum_raw(self, m):
        weights = {
            "return_10d_pct": float(settings.get("quant.momentum_weights.return_10d")),
            "return_20d_pct": float(settings.get("quant.momentum_weights.return_20d")),
            "return_50d_pct": float(settings.get("quant.momentum_weights.return_50d")),
            "return_60d_pct": float(settings.get("quant.momentum_weights.return_60d")),
            "return_120d_pct": float(settings.get("quant.momentum_weights.return_120d")),
        }
        values = [
            m.get(key) * weight
            for key, weight in weights.items()
            if m.get(key) is not None
        ]
        return sum(values) if values else None

    def _trend_raw(self, m):
        score = 0.0
        if m.get("above_ema20"):
            score += 1
        if m.get("above_ema50"):
            score += 1.5
        if m.get("above_ema200"):
            score += 2
        if m.get("ema20_above_50"):
            score += 1.5
        if m.get("ema50_above_200"):
            score += 2

        slope20 = m.get("ema20_slope_pct")
        slope50 = m.get("ema50_slope_pct")
        persistence = m.get("pct_above_ema20_20d")

        if slope20 is not None:
            score += slope20 * 0.5
        if slope50 is not None:
            score += slope50 * 0.7
        if persistence is not None:
            score += persistence / 100 * 2
        return score

    def _relative_strength_raw(self, m, benchmark):
        weights = {
            "return_20d_pct": float(settings.get("quant.relative_strength_weights.return_20d")),
            "return_60d_pct": float(settings.get("quant.relative_strength_weights.return_60d")),
            "return_120d_pct": float(settings.get("quant.relative_strength_weights.return_120d")),
        }
        score = 0.0
        found = False

        for key, weight in weights.items():
            stock = m.get(key)
            reference = benchmark.get(key)
            if stock is not None and reference is not None:
                score += (stock - reference) * weight
                found = True

        return score if found else None

    def _breakout_raw(self, m):
        position = m.get("range_position_52w")
        high20 = m.get("distance_20d_high_pct")
        high50 = m.get("distance_50d_high_pct")
        score = 0.0
        found = False

        if position is not None:
            score += position / 100 * 3
            found = True
        if high20 is not None:
            score += (max(-10, high20) + 10) / 10 * 2
            found = True
        if high50 is not None:
            score += (max(-15, high50) + 15) / 15 * 2
            found = True

        return score if found else None

    def _volume_raw(self, m):
        values = [
            value
            for value in [m.get("volume_ratio_20d"), m.get("volume_ratio_50d")]
            if value is not None
        ]
        if not values:
            return None
        cap = float(settings.get("quant.volume_ratio_cap"))
        return mean(min(value, cap) for value in values)

    def _volatility_raw(self, m):
        atr = m.get("atr_pct")
        vol20 = m.get("realized_vol_20d")

        if atr is None and vol20 is None:
            return None

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

    def _overextension_raw(self, m):
        score = 100.0
        rsi = m.get("rsi_14")
        d20 = m.get("distance_ema20_pct")
        d50 = m.get("distance_ema50_pct")

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

        if d50 is not None and d50 > 30:
            score -= 20

        return score

    def _percentiles(self, values):
        clean = [
            (symbol, value)
            for symbol, value in values
            if value is not None
        ]
        if not clean:
            return {}

        ordered = sorted(clean, key=lambda x: x[1])
        total = len(ordered)
        result = {}

        for index, (symbol, _) in enumerate(ordered):
            percentile = 100.0 if total == 1 else index / (total - 1) * 100
            result[symbol] = round(percentile, 2)
        return result

    def _weighted_score(self, q):
        weights = {
            "momentum": float(settings.get("quant.factor_weights.momentum")),
            "trend": float(settings.get("quant.factor_weights.trend")),
            "relative_strength": float(settings.get("quant.factor_weights.relative_strength")),
            "breakout": float(settings.get("quant.factor_weights.breakout")),
            "volume": float(settings.get("quant.factor_weights.volume")),
            "volatility_quality": float(settings.get("quant.factor_weights.volatility_quality")),
            "overextension_quality": float(settings.get("quant.factor_weights.overextension_quality")),
        }

        total = 0.0
        used = 0.0
        for key, weight in weights.items():
            value = q.get(key)
            if value is None:
                continue
            total += value * weight
            used += weight

        return 0.0 if used == 0 else round(total / used, 2)

    def _agreement(self, q):
        factor_names = {
            "momentum",
            "trend",
            "relative_strength",
            "breakout",
            "volume",
            "volatility_quality",
            "overextension_quality",
        }
        clean = [
            value
            for key, value in q.items()
            if key in factor_names and value is not None
        ]
        if not clean:
            return 0.0

        threshold = float(
            settings.get("quant.confidence.bullish_factor_threshold")
        )
        bullish = [value for value in clean if value >= threshold]
        return round(len(bullish) / len(clean) * 100, 2)

    def _signal_confidence(self, q):
        """Signal agreement/stability score, not probability of profit."""
        factor_names = {
            "momentum",
            "trend",
            "relative_strength",
            "breakout",
            "volume",
            "volatility_quality",
            "overextension_quality",
        }
        factors = [
            value
            for key, value in q.items()
            if key in factor_names and value is not None
        ]
        if not factors:
            return 0.0

        threshold = float(
            settings.get("quant.confidence.bullish_factor_threshold")
        )
        average_weight = float(
            settings.get("quant.confidence.factor_average_weight")
        )
        agreement_weight = float(
            settings.get("quant.confidence.agreement_weight")
        )

        average = mean(factors)
        agreement = (
            len([value for value in factors if value >= threshold])
            / len(factors)
            * 100
        )
        confidence = average * average_weight + agreement * agreement_weight
        return round(min(100, max(0, confidence)), 2)


quant_screener = QuantScreener()
