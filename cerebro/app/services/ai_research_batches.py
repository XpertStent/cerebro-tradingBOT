import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.services.ai_web_research import RESEARCH_SCHEMA, RESEARCH_SCHEMA_VERSION, ai_web_research
from app.services.openai_retry import is_retryable_openai_error, retry_delay
from app.services.settings import DEFINITIONS, settings


# Register the clustered-research control with the shared Settings registry.
# This is intentionally a separate key from the old per-symbol worker count so
# existing installations do not accidentally turn a saved value of 12 workers
# into 12 large parallel batch requests.
DEFINITIONS.setdefault(
    "ai.research.parallel_batches",
    {
        "section": "AI & Models",
        "subsection": "Research",
        "label": "Parallel Research Clusters",
        "type": "integer",
        "default": 4,
        "min": 1,
        "max": 12,
        "description": (
            "Number of clustered OpenAI research/news requests run in parallel. "
            "For example, 30 symbols with a value of 4 are split across 4 balanced "
            "requests; a value of 6 uses 6 balanced requests."
        ),
    },
)


BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": RESEARCH_SCHEMA,
        },
    },
    "required": ["results"],
    "additionalProperties": False,
}


class AIResearchBatchService:
    """Research many symbols with a small number of clustered web-search calls.

    Valid results are salvaged even when a model returns a malformed clustered
    response. Only duplicated/omitted symbols are retried in isolated recovery
    requests, so one bad row can no longer poison an otherwise-good cluster.
    """

    @property
    def parallel_batches(self):
        return max(1, int(settings.get("ai.research.parallel_batches")))

    def _partition(self, items, count):
        if not items:
            return []
        count = max(1, min(int(count), len(items)))
        base, remainder = divmod(len(items), count)
        batches = []
        cursor = 0
        for index in range(count):
            size = base + (1 if index < remainder else 0)
            batches.append(items[cursor:cursor + size])
            cursor += size
        return batches

    def _prompt(self, requests):
        payload = []
        for item in requests:
            payload.append({
                "symbol": item["symbol"],
                "company_name": item.get("company_name"),
                "relationships": item.get("relationships") or [],
                "market_snapshot": item.get("market_snapshot"),
                "quant_context": item.get("quant_context"),
            })

        return f"""
You are the research/news and evidence-validation layer for Cerebro, a
US-equity trading system. Research every company in this batch on the live web.

This is RESEARCH ONLY. Do not recommend BUY, SELL, HOLD, WATCH, IGNORE,
position sizes, allocations, or orders. The downstream portfolio model makes
those decisions independently.

For EACH symbol, use the supplied current market snapshot, relationship to the
portfolio, quant metrics and discontinuity events as context. The snapshot may
also include a currently held symbol that was not a quant candidate. Research
it with the same standard as every other symbol.

Prioritize evidence in this order:
1. SEC and government/regulatory sources
2. company investor-relations releases
3. Reuters/AP/Bloomberg and major financial press
4. specialist industry publications
5. other sources only when genuinely needed

Prioritize current earnings/guidance, M&A, regulatory or clinical news, major
contracts, products, management changes, material litigation, corporate
actions, material analyst actions, and directly relevant industry/macro news.
If discontinuity_events are supplied, investigate those dates specifically and
determine whether reliable evidence explains the price move. Never invent a
catalyst. If evidence is insufficient, use UNCERTAIN.

Ignore generic buy/sell articles, SEO listicles, duplicated syndication,
social-media speculation, Reddit and broad market roundups.

Do not put URLs or markdown citations in prose fields. Put evidence URLs only
in source_urls. Every high-materiality event should have at least one source
URL when reliable evidence exists. Keep each company's evidence separate.

Return exactly one result for every supplied symbol and no extra symbols.
Do not duplicate any symbol in the results array. Copy each supplied ticker
exactly as provided.

BATCH INPUT:
{json.dumps(payload, ensure_ascii=False, default=str)}

Return only the requested structured result.
""".strip()

    def _build_payload(self, research, request, consulted_sources):
        symbol = str(request["symbol"]).upper()
        research = dict(research)
        research["symbol"] = symbol

        quant_context = request.get("quant_context") or {}
        metrics = quant_context.get("metrics") or {}
        discontinuity_events = metrics.get("discontinuity_events") or []
        requires_event_review = bool(
            metrics.get("requires_event_review") or discontinuity_events
        )
        if not requires_event_review:
            research["price_anomaly_assessment"] = {
                "classification": "NO_EXTREME_MOVE",
                "confidence": 1.0,
                "explanation": (
                    "Cerebro did not supply an extreme or discontinuous "
                    "price move requiring event review."
                ),
                "source_urls": [],
            }

        sources, source_id_by_url = ai_web_research._build_source_index(
            research,
            consulted_sources,
        )
        research = ai_web_research._replace_urls_with_ids(
            research,
            source_id_by_url,
        )

        signature = ai_web_research._signature(
            symbol=symbol,
            company_name=request.get("company_name"),
            quant_context=quant_context,
            relationships=request.get("relationships") or [],
        )
        payload = {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "symbol": symbol,
            "model": ai_web_research.model,
            "status": "READY",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cache": "MISS",
            "research": research,
            "sources": sources,
            "source_count": len(sources),
            "consulted_source_count": len(consulted_sources),
            "query_signature": signature,
        }
        ai_web_research._save_cache(symbol, payload)
        return payload

    def _research_batch_once(self, requests):
        """Return valid rows plus unresolved symbols instead of failing a batch.

        Duplicate expected symbols are deliberately not trusted: both copies are
        discarded and that symbol is queued for isolated recovery. Unexpected
        symbols are ignored. Unique valid rows are retained immediately.
        """
        response = ai_web_research._client().responses.create(
            model=ai_web_research.model,
            reasoning={
                "effort": str(settings.get("ai.research.reasoning_effort")),
            },
            tools=[{
                "type": "web_search",
                "search_context_size": str(settings.get("ai.research.search_context_size")),
            }],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            input=self._prompt(requests),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "equity_research_batch",
                    "strict": True,
                    "schema": BATCH_SCHEMA,
                }
            },
        )

        parsed = json.loads(response.output_text)
        results = parsed.get("results") or []
        request_map = {
            str(item["symbol"]).upper(): item
            for item in requests
        }
        expected = set(request_map)
        consulted_sources = ai_web_research._extract_consulted_sources(response)

        counts = {}
        unexpected = []
        for research in results:
            symbol = str(research.get("symbol") or "").upper()
            if symbol in expected:
                counts[symbol] = counts.get(symbol, 0) + 1
            elif symbol:
                unexpected.append(symbol)

        duplicates = {symbol for symbol, count in counts.items() if count > 1}
        by_symbol = {}
        for research in results:
            symbol = str(research.get("symbol") or "").upper()
            if symbol not in expected or symbol in duplicates:
                continue
            if symbol in by_symbol:
                continue
            by_symbol[symbol] = self._build_payload(
                research,
                request_map[symbol],
                consulted_sources,
            )

        unresolved_symbols = sorted(expected - set(by_symbol))
        issues = []
        if duplicates:
            issues.append(
                "duplicate symbol(s): " + ", ".join(sorted(duplicates))
            )
        omitted = sorted(symbol for symbol in unresolved_symbols if symbol not in duplicates)
        if omitted:
            issues.append("omitted symbol(s): " + ", ".join(omitted))
        if unexpected:
            issues.append(
                "unexpected symbol(s): " + ", ".join(sorted(set(unexpected)))
            )

        return {
            "results": by_symbol,
            "unresolved": [request_map[symbol] for symbol in unresolved_symbols],
            "issues": issues,
        }

    def _request_with_retry(self, requests, batch_number, progress_callback=None, recovery=False):
        max_attempts = 4
        symbols = [str(item["symbol"]).upper() for item in requests]
        for attempt in range(1, max_attempts + 1):
            try:
                return self._research_batch_once(requests)
            except Exception as exc:
                if attempt >= max_attempts or not is_retryable_openai_error(exc):
                    raise

                delay, retry_source, provider_delay = retry_delay(
                    exc,
                    attempt=attempt,
                    base_delay=2.0,
                    safety_seconds=1.0,
                )
                if progress_callback:
                    progress_callback(
                        stage="RESEARCH_RETRY",
                        current_symbol=None,
                        status="RETRY",
                        batch_number=batch_number,
                        batch_symbols=symbols,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_seconds=round(delay, 3),
                        provider_retry_after_seconds=(
                            round(provider_delay, 3)
                            if provider_delay is not None else None
                        ),
                        retry_source=retry_source,
                        recovery=recovery,
                        error=str(exc),
                    )
                time.sleep(delay)
        raise RuntimeError("Research request retry loop exhausted")

    def _recover_one(self, request, batch_number, progress_callback=None, prior_issue=None):
        symbol = str(request["symbol"]).upper()
        consistency_attempts = 2
        last_issue = prior_issue or "clustered response was incomplete"

        for recovery_attempt in range(1, consistency_attempts + 1):
            if progress_callback:
                progress_callback(
                    stage="RESEARCH_RECOVERY",
                    current_symbol=symbol,
                    status="RECOVERING",
                    batch_number=batch_number,
                    batch_symbols=[symbol],
                    recovery_attempt=recovery_attempt,
                    recovery_max_attempts=consistency_attempts,
                    error=last_issue,
                )
            try:
                packet = self._request_with_retry(
                    [request],
                    batch_number,
                    progress_callback,
                    recovery=True,
                )
            except Exception as exc:
                last_issue = str(exc)
                continue

            result = packet.get("results") or {}
            if symbol in result:
                return result[symbol]
            last_issue = "; ".join(packet.get("issues") or []) or (
                f"isolated research response still omitted {symbol}"
            )

        return {
            "symbol": symbol,
            "status": "ERROR",
            "error": (
                "Research model output remained inconsistent after isolated "
                f"recovery for {symbol}: {last_issue}"
            ),
            "research": None,
            "sources": [],
            "source_count": 0,
            "consulted_source_count": 0,
        }

    def _research_batch_with_retry(self, batch, batch_number, progress_callback=None):
        symbols = [str(item["symbol"]).upper() for item in batch]
        resolved = {}
        unresolved = list(batch)
        cluster_issue = None

        try:
            packet = self._request_with_retry(
                batch,
                batch_number,
                progress_callback,
            )
            resolved.update(packet.get("results") or {})
            unresolved = packet.get("unresolved") or []
            cluster_issue = "; ".join(packet.get("issues") or []) or None
        except Exception as exc:
            # A cluster-level API failure should not waste every symbol. Fall
            # back to isolated recovery so successful symbols can still proceed.
            cluster_issue = str(exc)
            unresolved = list(batch)

        if unresolved and progress_callback:
            progress_callback(
                stage="RESEARCH_RECOVERY",
                current_symbol=None,
                status="STARTING",
                batch_number=batch_number,
                batch_symbols=[str(item["symbol"]).upper() for item in unresolved],
                error=cluster_issue,
            )

        for request in unresolved:
            symbol = str(request["symbol"]).upper()
            resolved[symbol] = self._recover_one(
                request,
                batch_number,
                progress_callback,
                prior_issue=cluster_issue,
            )

        # Defensive guarantee: every requested symbol exits this worker with a
        # READY or ERROR payload, never silently disappears.
        for request in batch:
            symbol = str(request["symbol"]).upper()
            if symbol not in resolved:
                resolved[symbol] = {
                    "symbol": symbol,
                    "status": "ERROR",
                    "error": f"Research recovery produced no result for {symbol}",
                    "research": None,
                    "sources": [],
                    "source_count": 0,
                    "consulted_source_count": 0,
                }
        return resolved

    def research_many(self, requests, progress_callback=None):
        requests = [item for item in requests if item.get("symbol")]
        if not requests:
            return {}

        output = {}
        pending = []
        total = len(requests)
        complete = 0

        for item in requests:
            symbol = str(item["symbol"]).upper()
            item = dict(item)
            item["symbol"] = symbol
            signature = ai_web_research._signature(
                symbol=symbol,
                company_name=item.get("company_name"),
                quant_context=item.get("quant_context") or {},
                relationships=item.get("relationships") or [],
            )
            cached = ai_web_research._load_cache(
                symbol=symbol,
                signature=signature,
            )
            if cached:
                output[symbol] = cached
                complete += 1
                if progress_callback:
                    progress_callback(
                        stage="RESEARCH",
                        current_symbol=symbol,
                        status="READY",
                        cache="HIT",
                        total=total,
                        complete=complete,
                        ready=sum(1 for value in output.values() if value.get("status") == "READY"),
                        errors=sum(1 for value in output.values() if value.get("status") == "ERROR"),
                        in_flight=0,
                    )
            else:
                pending.append(item)

        batches = self._partition(pending, self.parallel_batches)
        if progress_callback:
            progress_callback(
                stage="RESEARCH",
                current_symbol=None,
                status="STARTING",
                total=total,
                complete=complete,
                batch_count=len(batches),
                in_flight=len(batches),
            )

        if not batches:
            return output

        with ThreadPoolExecutor(max_workers=len(batches)) as executor:
            futures = {
                executor.submit(
                    self._research_batch_with_retry,
                    batch,
                    index,
                    progress_callback,
                ): (index, batch)
                for index, batch in enumerate(batches, start=1)
            }

            for future in as_completed(futures):
                batch_number, batch = futures[future]
                symbols = [str(item["symbol"]).upper() for item in batch]
                try:
                    batch_output = future.result()
                except Exception as exc:
                    # Last-resort guard. Normally _research_batch_with_retry
                    # returns per-symbol errors rather than throwing.
                    batch_output = {
                        symbol: {
                            "symbol": symbol,
                            "status": "ERROR",
                            "error": str(exc),
                            "research": None,
                            "sources": [],
                            "source_count": 0,
                            "consulted_source_count": 0,
                        }
                        for symbol in symbols
                    }

                output.update(batch_output)
                for symbol in symbols:
                    complete += 1
                    status = (output.get(symbol) or {}).get("status") or "ERROR"
                    if progress_callback:
                        progress_callback(
                            stage="RESEARCH",
                            current_symbol=symbol,
                            status=status,
                            cache=(output.get(symbol) or {}).get("cache"),
                            error=(output.get(symbol) or {}).get("error"),
                            batch_number=batch_number,
                            batch_symbols=symbols,
                            total=total,
                            complete=complete,
                            ready=sum(1 for value in output.values() if value.get("status") == "READY"),
                            errors=sum(1 for value in output.values() if value.get("status") == "ERROR"),
                            in_flight=max(0, len(futures) - sum(1 for f in futures if f.done())),
                        )

        if progress_callback:
            progress_callback(
                stage="RESEARCH_COMPLETE",
                current_symbol=None,
                status="COMPLETE",
                total=total,
                complete=complete,
                ready=sum(1 for value in output.values() if value.get("status") == "READY"),
                errors=sum(1 for value in output.values() if value.get("status") == "ERROR"),
                batch_count=len(batches),
                in_flight=0,
            )
        return output


ai_research_batches = AIResearchBatchService()
