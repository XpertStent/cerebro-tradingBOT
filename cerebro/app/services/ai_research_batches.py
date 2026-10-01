import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.services.ai_web_research import RESEARCH_SCHEMA, RESEARCH_SCHEMA_VERSION, ai_web_research
from app.services.settings import settings


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

    The configured parallel batch count means exactly what the operator sees in
    Settings: with 30 uncached symbols and a value of 4, Cerebro splits the
    symbols as evenly as possible across four parallel OpenAI research calls.
    A value of 6 creates six parallel calls. Cached symbols are removed before
    clustering, so the actual request count can be lower on repeat runs.
    """

    @property
    def parallel_batches(self):
        return max(1, int(settings.get("ai.research.parallel_batches")))

    def _is_retryable(self, exc):
        text = str(exc).lower()
        return any(marker in text for marker in (
            "429", "rate limit", "rate_limit", "too many requests",
            "timeout", "timed out", "temporarily unavailable",
            "502", "503", "504", "connection reset", "connection error",
        ))

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
You are the research/news and evidence-validation layer for Cerebro, an
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

BATCH INPUT:
{json.dumps(payload, ensure_ascii=False, default=str)}

Return only the requested structured result.
""".strip()

    def _research_batch_once(self, requests):
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
        expected = {str(item["symbol"]).upper() for item in requests}
        seen = set()
        by_symbol = {}
        consulted_sources = ai_web_research._extract_consulted_sources(response)

        request_map = {
            str(item["symbol"]).upper(): item
            for item in requests
        }

        for research in results:
            symbol = str(research.get("symbol") or "").upper()
            research["symbol"] = symbol
            if symbol not in expected:
                raise RuntimeError(f"Research batch returned unexpected symbol: {symbol}")
            if symbol in seen:
                raise RuntimeError(f"Research batch returned duplicate symbol: {symbol}")
            seen.add(symbol)

            request = request_map[symbol]
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
            by_symbol[symbol] = payload

        missing = sorted(expected - seen)
        if missing:
            raise RuntimeError(
                "Research batch omitted symbol(s): " + ", ".join(missing)
            )
        return by_symbol

    def _research_batch_with_retry(self, batch, batch_number, progress_callback=None):
        max_attempts = 4
        symbols = [str(item["symbol"]).upper() for item in batch]

        for attempt in range(1, max_attempts + 1):
            try:
                return self._research_batch_once(batch)
            except Exception as exc:
                if attempt >= max_attempts or not self._is_retryable(exc):
                    raise
                delay = 2.0 * (2 ** (attempt - 1)) + random.uniform(0.0, 1.0)
                if progress_callback:
                    progress_callback(
                        stage="RESEARCH_RETRY",
                        current_symbol=None,
                        status="RETRY",
                        batch_number=batch_number,
                        batch_symbols=symbols,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_seconds=round(delay, 1),
                        error=str(exc),
                    )
                time.sleep(delay)

        raise RuntimeError("Research batch retry loop exhausted")

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
                    output.update(batch_output)
                    for symbol in symbols:
                        complete += 1
                        if progress_callback:
                            progress_callback(
                                stage="RESEARCH",
                                current_symbol=symbol,
                                status=(output.get(symbol) or {}).get("status") or "READY",
                                cache=(output.get(symbol) or {}).get("cache"),
                                batch_number=batch_number,
                                batch_symbols=symbols,
                                total=total,
                                complete=complete,
                                ready=sum(1 for value in output.values() if value.get("status") == "READY"),
                                errors=sum(1 for value in output.values() if value.get("status") == "ERROR"),
                                in_flight=max(0, len(futures) - sum(1 for f in futures if f.done())),
                            )
                except Exception as exc:
                    for symbol in symbols:
                        output[symbol] = {
                            "symbol": symbol,
                            "status": "ERROR",
                            "error": str(exc),
                            "research": None,
                            "sources": [],
                            "source_count": 0,
                            "consulted_source_count": 0,
                        }
                        complete += 1
                        if progress_callback:
                            progress_callback(
                                stage="RESEARCH",
                                current_symbol=symbol,
                                status="ERROR",
                                error=str(exc),
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
