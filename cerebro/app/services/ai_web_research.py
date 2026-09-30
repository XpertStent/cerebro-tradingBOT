import hashlib
import json
import os
import time
import urllib.parse

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI


RESEARCH_SCHEMA_VERSION = 2


SOURCE_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
        },
        "source_urls": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "text",
        "source_urls",
    ],
    "additionalProperties": False,
}


RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
        },

        "research_status": {
            "type": "string",
            "enum": [
                "COMPLETE",
                "PARTIAL",
                "NO_MATERIAL_INFORMATION",
            ],
        },

        "company_summary": {
            "type": "string",
        },

        "material_events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_date": {
                        "type": [
                            "string",
                            "null",
                        ],
                    },

                    "event_type": {
                        "type": "string",
                        "enum": [
                            "EARNINGS",
                            "GUIDANCE",
                            "SEC_FILING",
                            "M_AND_A",
                            "CLINICAL_TRIAL",
                            "REGULATORY",
                            "CONTRACT",
                            "PRODUCT",
                            "MANAGEMENT",
                            "LITIGATION",
                            "CORPORATE_ACTION",
                            "ANALYST_ACTION",
                            "MACRO_EXPOSURE",
                            "OTHER",
                        ],
                    },

                    "headline": {
                        "type": "string",
                    },

                    "summary": {
                        "type": "string",
                    },

                    "materiality": {
                        "type": "string",
                        "enum": [
                            "HIGH",
                            "MEDIUM",
                            "LOW",
                        ],
                    },

                    "explains_price_move": {
                        "type": [
                            "boolean",
                            "null",
                        ],
                    },

                    "source_urls": {
                        "type": "array",
                        "items": {
                            "type": "string",
                        },
                    },
                },

                "required": [
                    "event_date",
                    "event_type",
                    "headline",
                    "summary",
                    "materiality",
                    "explains_price_move",
                    "source_urls",
                ],

                "additionalProperties":
                    False,
            },
        },

        "bullish_factors": {
            "type": "array",
            "items":
                SOURCE_REF_SCHEMA,
        },

        "bearish_factors": {
            "type": "array",
            "items":
                SOURCE_REF_SCHEMA,
        },

        "uncertainties": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },

        "price_anomaly_assessment": {
            "type": "object",
            "properties": {
                "classification": {
                    "type": "string",
                    "enum": [
                        "REAL_EVENT",
                        "CORPORATE_ACTION",
                        "LIKELY_DATA_ANOMALY",
                        "UNCERTAIN",
                        "NO_EXTREME_MOVE",
                    ],
                },

                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },

                "explanation": {
                    "type": "string",
                },

                "source_urls": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
            },

            "required": [
                "classification",
                "confidence",
                "explanation",
                "source_urls",
            ],

            "additionalProperties":
                False,
        },

        "context_quality": {
            "type": "object",
            "properties": {
                "sufficient_for_decision_model": {
                    "type": "boolean",
                },

                "missing_information": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                },
            },

            "required": [
                "sufficient_for_decision_model",
                "missing_information",
            ],

            "additionalProperties":
                False,
        },
    },

    "required": [
        "symbol",
        "research_status",
        "company_summary",
        "material_events",
        "bullish_factors",
        "bearish_factors",
        "uncertainties",
        "price_anomaly_assessment",
        "context_quality",
    ],

    "additionalProperties":
        False,
}


class AIWebResearchService:

    def __init__(
        self,
        cache_dir="/data/ai_research",
        ttl_seconds=3600,
        max_workers=4,
    ):
        self.cache_dir = Path(
            cache_dir
        )

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.ttl_seconds = (
            ttl_seconds
        )

        self.max_workers = (
            max_workers
        )

        self.model = os.getenv(
            "OPENAI_RESEARCH_MODEL",
            "gpt-5.6-luna",
        )

    def _client(self):
        api_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured"
            )

        return OpenAI(
            api_key=api_key
        )

    def _cache_path(
        self,
        symbol,
    ):
        safe = (
            str(symbol)
            .upper()
            .replace(".", "_")
        )

        return (
            self.cache_dir
            / f"{safe}.json"
        )

    def _signature(
        self,
        *,
        symbol,
        company_name,
        quant_context,
        relationships,
    ):
        raw = json.dumps(
            {
                "schema_version":
                    RESEARCH_SCHEMA_VERSION,

                "symbol":
                    symbol,

                "company_name":
                    company_name,

                "quant_context":
                    quant_context,

                "relationships":
                    relationships,
            },
            sort_keys=True,
            default=str,
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def _load_cache(
        self,
        *,
        symbol,
        signature,
    ):
        path = self._cache_path(
            symbol
        )

        if not path.exists():
            return None

        try:
            age = (
                time.time()
                - path.stat().st_mtime
            )

            if age > self.ttl_seconds:
                return None

            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                payload.get(
                    "query_signature"
                )
                != signature
            ):
                return None

            payload["cache"] = "HIT"

            return payload

        except Exception:
            return None

    def _save_cache(
        self,
        symbol,
        payload,
    ):
        path = self._cache_path(
            symbol
        )

        temp = path.with_suffix(
            ".tmp"
        )

        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        temp.replace(
            path
        )

    def _canonical_url(
        self,
        url,
    ):
        if not url:
            return None

        try:
            parsed = urllib.parse.urlsplit(
                str(url)
            )

            query = urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )

            query = [
                (key, value)
                for key, value in query
                if not key.lower().startswith(
                    "utm_"
                )
                and key.lower() not in {
                    "source",
                    "ref",
                    "referrer",
                }
            ]

            return urllib.parse.urlunsplit((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                urllib.parse.urlencode(query),
                "",
            ))

        except Exception:
            return str(url)

    def _domain(
        self,
        url,
    ):
        try:
            return (
                urllib.parse.urlsplit(
                    url
                )
                .netloc
                .lower()
                .removeprefix("www.")
            )

        except Exception:
            return ""

    def _source_quality(
        self,
        url,
    ):
        domain = self._domain(
            url
        )

        if domain == "sec.gov":
            return "PRIMARY"

        if domain.endswith(
            ".gov"
        ):
            return "PRIMARY"

        if (
            domain.startswith("ir.")
            or "investor" in domain
        ):
            return "PRIMARY"

        if domain in {
            "reuters.com",
            "apnews.com",
            "bloomberg.com",
            "wsj.com",
            "ft.com",
        }:
            return "HIGH"

        if domain in {
            "finance.yahoo.com",
            "cnbc.com",
            "marketwatch.com",
            "investing.com",
        }:
            return "MEDIUM"

        return "SUPPLEMENTAL"

    def _quality_rank(
        self,
        quality,
    ):
        return {
            "PRIMARY": 0,
            "HIGH": 1,
            "MEDIUM": 2,
            "SUPPLEMENTAL": 3,
        }.get(
            quality,
            4,
        )

    def _extract_consulted_sources(
        self,
        response,
    ):
        sources = {}

        for item in (
            getattr(
                response,
                "output",
                None,
            )
            or []
        ):
            item_type = getattr(
                item,
                "type",
                None,
            )

            if item_type != "web_search_call":
                continue

            action = getattr(
                item,
                "action",
                None,
            )

            if not action:
                continue

            action_sources = getattr(
                action,
                "sources",
                None,
            )

            if not action_sources:
                continue

            for source in action_sources:
                raw_url = getattr(
                    source,
                    "url",
                    None,
                )

                title = getattr(
                    source,
                    "title",
                    None,
                )

                if raw_url is None and isinstance(
                    source,
                    dict,
                ):
                    raw_url = source.get(
                        "url"
                    )

                    title = source.get(
                        "title"
                    )

                url = self._canonical_url(
                    raw_url
                )

                if not url:
                    continue

                sources[url] = {
                    "title":
                        title,

                    "url":
                        url,
                }

        return sources

    def _collect_cited_urls(
        self,
        research,
    ):
        urls = []

        def add(values):
            for value in (
                values
                or []
            ):
                url = self._canonical_url(
                    value
                )

                if (
                    url
                    and url not in urls
                ):
                    urls.append(
                        url
                    )

        for event in (
            research.get(
                "material_events"
            )
            or []
        ):
            add(
                event.get(
                    "source_urls"
                )
            )

        for key in (
            "bullish_factors",
            "bearish_factors",
        ):
            for factor in (
                research.get(key)
                or []
            ):
                add(
                    factor.get(
                        "source_urls"
                    )
                )

        assessment = (
            research.get(
                "price_anomaly_assessment"
            )
            or {}
        )

        add(
            assessment.get(
                "source_urls"
            )
        )

        return urls

    def _build_source_index(
        self,
        research,
        consulted_sources,
    ):
        cited_urls = (
            self._collect_cited_urls(
                research
            )
        )

        sources = []

        for url in cited_urls:
            consulted = (
                consulted_sources.get(
                    url
                )
                or {}
            )

            quality = (
                self._source_quality(
                    url
                )
            )

            sources.append({
                "url":
                    url,

                "title":
                    consulted.get(
                        "title"
                    ),

                "domain":
                    self._domain(
                        url
                    ),

                "quality":
                    quality,
            })

        sources.sort(
            key=lambda item: (
                self._quality_rank(
                    item["quality"]
                ),
                item["domain"],
                item["url"],
            )
        )

        source_id_by_url = {}

        for index, item in enumerate(
            sources,
            start=1,
        ):
            source_id = (
                f"src_{index}"
            )

            item["id"] = (
                source_id
            )

            source_id_by_url[
                item["url"]
            ] = source_id

        return (
            sources,
            source_id_by_url,
        )

    def _replace_urls_with_ids(
        self,
        research,
        source_id_by_url,
    ):
        def ids(values):
            output = []

            for value in (
                values
                or []
            ):
                url = self._canonical_url(
                    value
                )

                source_id = (
                    source_id_by_url.get(
                        url
                    )
                )

                if (
                    source_id
                    and source_id
                    not in output
                ):
                    output.append(
                        source_id
                    )

            return output

        for event in (
            research.get(
                "material_events"
            )
            or []
        ):
            event[
                "source_ids"
            ] = ids(
                event.pop(
                    "source_urls",
                    [],
                )
            )

        for key in (
            "bullish_factors",
            "bearish_factors",
        ):
            for factor in (
                research.get(key)
                or []
            ):
                factor[
                    "source_ids"
                ] = ids(
                    factor.pop(
                        "source_urls",
                        [],
                    )
                )

        assessment = (
            research.get(
                "price_anomaly_assessment"
            )
            or {}
        )

        assessment[
            "source_ids"
        ] = ids(
            assessment.pop(
                "source_urls",
                [],
            )
        )

        return research

    def _prompt(
        self,
        *,
        symbol,
        company_name,
        quant_context,
        relationships,
    ):
        return f"""
You are the research and evidence-validation layer
for an automated US equity trading system.

Research this company on the live web.

SYMBOL:
{symbol}

COMPANY:
{company_name or "Unknown"}

RELATIONSHIPS:
{json.dumps(relationships)}

QUANT / MARKET CONTEXT:
{json.dumps(quant_context, default=str)}

Your job is NOT to recommend BUY, SELL, HOLD,
position size, or any trade.

Your job is to discover and structure material
facts the downstream portfolio decision model
needs.

Prioritize evidence in this order:
1. SEC and government/regulatory sources
2. company investor-relations releases
3. Reuters/AP/Bloomberg and major financial press
4. specialist industry publications
5. other sources only when needed

Prioritize:
- earnings and guidance
- acquisitions or takeover activity
- FDA / regulatory / clinical developments
- major contracts
- product launches or failures
- management changes
- material litigation or investigations
- corporate actions
- genuinely material analyst actions
- meaningful industry or macro developments
  directly affecting this company

Ignore or heavily deprioritize:
- generic "should you buy" articles
- listicles
- SEO stock articles
- duplicated syndicated stories
- social-media speculation
- Reddit
- broad market roundups unless directly material

If quant_context contains discontinuity_events,
specifically investigate those dates and determine
whether reliable evidence explains the move.

Do not assume an extreme price move is bad data.
Do not invent a catalyst.

If reliable evidence is insufficient, classify the
price anomaly as UNCERTAIN.

IMPORTANT SOURCE RULES:

- Do NOT place markdown citations or URLs inside
  headline, summary, explanation, text, or other
  prose fields.

- Put evidence URLs ONLY in source_urls.

- Every HIGH materiality event should have at
  least one source URL when evidence exists.

- Prefer primary evidence over commentary.

- Do not add a URL unless you actually used that
  source to support the statement.

Separate facts from uncertainty.

Return only the requested structured result.
""".strip()

    def research(
        self,
        *,
        symbol,
        company_name=None,
        quant_context=None,
        relationships=None,
    ):
        symbol = str(
            symbol
        ).upper()

        quant_context = (
            quant_context
            or {}
        )

        relationships = (
            relationships
            or []
        )

        signature = self._signature(
            symbol=symbol,
            company_name=company_name,
            quant_context=quant_context,
            relationships=relationships,
        )

        cached = self._load_cache(
            symbol=symbol,
            signature=signature,
        )

        if cached:
            return cached

        client = self._client()

        response = (
            client.responses.create(
                model=self.model,

                reasoning={
                    "effort":
                        "medium",
                },

                tools=[{
                    "type":
                        "web_search",

                    "search_context_size":
                        "medium",
                }],

                tool_choice="required",

                include=[
                    "web_search_call.action.sources"
                ],

                input=self._prompt(
                    symbol=symbol,
                    company_name=company_name,
                    quant_context=quant_context,
                    relationships=relationships,
                ),

                text={
                    "format": {
                        "type":
                            "json_schema",

                        "name":
                            "equity_research_context",

                        "strict":
                            True,

                        "schema":
                            RESEARCH_SCHEMA,
                    }
                },
            )
        )

        research = json.loads(
            response.output_text
        )

        #
        # Price-anomaly classification is only meaningful when
        # Cerebro actually detected something requiring review.
        #
        metrics = (
            quant_context.get(
                "metrics"
            )
            or {}
        )

        discontinuity_events = (
            metrics.get(
                "discontinuity_events"
            )
            or []
        )

        requires_event_review = bool(
            metrics.get(
                "requires_event_review"
            )
            or discontinuity_events
        )

        if not requires_event_review:
            research[
                "price_anomaly_assessment"
            ] = {
                "classification":
                    "NO_EXTREME_MOVE",

                "confidence":
                    1.0,

                "explanation":
                    (
                        "Cerebro did not supply an "
                        "extreme or discontinuous "
                        "price move requiring "
                        "event review."
                    ),

                "source_urls":
                    [],
            }

        consulted_sources = (
            self._extract_consulted_sources(
                response
            )
        )

        (
            sources,
            source_id_by_url,
        ) = self._build_source_index(
            research,
            consulted_sources,
        )

        research = (
            self._replace_urls_with_ids(
                research,
                source_id_by_url,
            )
        )

        payload = {
            "schema_version":
                RESEARCH_SCHEMA_VERSION,

            "symbol":
                symbol,

            "model":
                self.model,

            "status":
                "READY",

            "fetched_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "cache":
                "MISS",

            "research":
                research,

            #
            # Only sources actually cited by the
            # structured research survive here.
            #
            "sources":
                sources,

            "source_count":
                len(sources),

            "consulted_source_count":
                len(
                    consulted_sources
                ),

            "query_signature":
                signature,
        }

        self._save_cache(
            symbol,
            payload,
        )

        return payload

    def research_many(
        self,
        requests,
    ):
        requests = [
            item
            for item in requests
            if item.get("symbol")
        ]

        output = {}

        if not requests:
            return output

        with ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:

            futures = {
                executor.submit(
                    self.research,

                    symbol=
                        item["symbol"],

                    company_name=
                        item.get(
                            "company_name"
                        ),

                    quant_context=
                        (
                            item.get(
                                "quant_context"
                            )
                            or {}
                        ),

                    relationships=
                        (
                            item.get(
                                "relationships"
                            )
                            or []
                        ),
                ):
                item["symbol"]

                for item in requests
            }

            for future in (
                as_completed(
                    futures
                )
            ):
                symbol = (
                    futures[
                        future
                    ]
                )

                try:
                    output[
                        symbol
                    ] = future.result()

                except Exception as exc:
                    output[
                        symbol
                    ] = {
                        "symbol":
                            symbol,

                        "status":
                            "ERROR",

                        "error":
                            str(exc),

                        "research":
                            None,

                        "sources":
                            [],
                    }

        return output


ai_web_research = (
    AIWebResearchService()
)
