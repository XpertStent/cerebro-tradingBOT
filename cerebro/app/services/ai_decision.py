import json
import time
from copy import deepcopy
from datetime import datetime, timezone

from openai import OpenAI

from app.services.ai_run_context import ai_run_context
from app.services.openai_retry import is_retryable_openai_error, retry_delay
from app.services.settings import DEFINITIONS, settings


DEFINITIONS.setdefault(
    "ai.decision.web_search_enabled",
    {
        "section": "AI & Models",
        "subsection": "Decision Model",
        "label": "Decision Model Web Research",
        "type": "boolean",
        "default": True,
        "description": (
            "Allow the final portfolio decision model to independently verify or augment "
            "the clustered research with live web search before returning decisions."
        ),
    },
)

DEFINITIONS.setdefault(
    "ai.decision.search_context_size",
    {
        "section": "AI & Models",
        "subsection": "Decision Model",
        "label": "Decision Web Search Context Size",
        "type": "enum",
        "default": "medium",
        "options": ["low", "medium", "high"],
        "description": "Web-search context size available to the final decision model.",
    },
)


DECISION_SCHEMA_VERSION = 4

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "portfolio_summary": {"type": "string"},
        "market_summary": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": [
                            "BUY", "ADD", "HOLD", "REDUCE", "SELL", "WATCH", "IGNORE",
                        ],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "reasoning": {"type": "string"},
                    "what_changed": {"type": ["string", "null"]},
                    "thesis_update": {"type": ["string", "null"]},
                    "thesis_invalidation": {"type": ["string", "null"]},
                    "desired_exposure_pct": {
                        "type": ["number", "null"],
                        "minimum": 0,
                        "maximum": 100,
                    },
                },
                "required": [
                    "symbol",
                    "action",
                    "confidence",
                    "reasoning",
                    "what_changed",
                    "thesis_update",
                    "thesis_invalidation",
                    "desired_exposure_pct",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["portfolio_summary", "market_summary", "decisions"],
    "additionalProperties": False,
}


class AIDecisionEngine:
    """Generate portfolio intents only.

    This service never places orders. Its output is an advisory/intent layer
    that must pass through Cerebro's deterministic proposal and risk pipeline
    before any execution can occur.
    """

    def _client(self):
        api_key = settings.get("openai.api_key")
        if not api_key:
            raise RuntimeError("OpenAI API key is not configured")
        return OpenAI(api_key=api_key)

    def _prompt(self, context, *, web_search_enabled):
        web_search_instruction = (
            "You ALSO have live web search available. Independently verify or augment "
            "the clustered research when it materially improves a decision, especially "
            "for recent earnings/guidance, regulatory events, M&A, major contracts, "
            "management changes, unusual price moves, conflicting evidence, stale data, "
            "or symbols whose upstream research failed. Treat supplied structured research "
            "as a strong evidence layer, not as a restriction on your own analysis. Use "
            "reliable primary/major-news sources and do not invent facts."
            if web_search_enabled
            else
            "Live web search is disabled for this decision request. Base external factual "
            "claims on the supplied structured context and do not invent missing facts."
        )

        return f"""
You are the portfolio decision layer for Cerebro, an automated US-equity
trading system.

You receive deterministic portfolio state, broker state, current holdings,
pending orders, the latest quant candidate set, persistent Monitored Securities,
structured company research, prior theses, recent decisions, rejections,
current market state, and the CURRENT DETERMINISTIC RISK POLICY that any
proposed order must pass.

Rejection history has distinct meanings: USER_REJECTED is operator feedback;
use its reason when present without inventing a reason or treating it as a
permanent ban. CURRENT_SET_RISK_POLICY_BLOCKED means the then-current editable
risk policy blocked the proposal; reassess against the current policy.

When technical_analysis is supplied, it is advisory evidence from completed
daily candles, not a trading instruction. FORMING is unconfirmed; neutral
formations have no directional breakout yet. Respect recognition and confirmation
dates, data provenance and invalidation conditions. Library values and geometry
checks are not win probabilities. Adjusted pattern levels are not raw executable
order prices. No pattern trigger is armed. Do not let overlapping pattern labels
outvote portfolio context, research or deterministic risk constraints.

Your job is to produce PORTFOLIO INTENTS ONLY. You never place orders and you
never bypass deterministic risk controls.

You are explicitly expected to perform independent investment analysis and
reasoning on each supplied candidate. Synthesize the evidence; compare signals,
quality, uncertainty, portfolio fit, and risk. Do not merely restate quant flags
or mechanically copy prior decisions.

{web_search_instruction}

Allowed actions:
- BUY: initiate a new position in a symbol not currently held.
- ADD: increase an existing holding.
- HOLD: keep an existing holding broadly unchanged.
- REDUCE: decrease an existing holding without fully exiting.
- SELL: fully exit an existing holding.
- WATCH: no order now, but the candidate remains sufficiently interesting to
  monitor for a future trigger, better entry, event resolution, or stronger
  evidence. WATCH is an operator-approvable monitoring action; once approved,
  Cerebro persists the symbol in Monitored Securities and includes it in later
  decision runs until the operator removes it.
- IGNORE: no order and no monitoring thesis is warranted for this candidate in
  the current run. Use this when the setup is weak, low-quality, irrelevant,
  redundant, or not worth continued attention.

Rules:
1. Return exactly one decision for every candidate supplied in `candidates`.
2. Do not invent symbols that are absent from the supplied candidate set.
3. Current holdings must use ADD, HOLD, REDUCE, or SELL. Do not use
   BUY/WATCH/IGNORE for a currently held symbol because every holding must be
   actively managed.
4. Non-held names may use BUY, WATCH, or IGNORE. Do not use
   ADD/HOLD/REDUCE/SELL for a non-held symbol.
5. Pending orders are context, not permission to duplicate an order. Avoid a
   new action that blindly duplicates a materially equivalent pending order.
6. Quant scores are signals, not probabilities of profit. Research evidence,
   portfolio concentration, available cash, existing thesis, persistent
   watchlist interest, and uncertainty all matter.
7. A price discontinuity marked as a real event is not automatically bullish
   or bearish. Investigate or use the supplied research assessment.
8. Missing/failed upstream research is NOT by itself a command to WATCH. When
   web search is enabled, independently investigate material gaps before
   deciding. Otherwise use the remaining evidence. WATCH only when the name is
   genuinely worth monitoring; use IGNORE when it is not.
9. `desired_exposure_pct` is a target percent of total portfolio value after
   the proposed action. Use null for WATCH and IGNORE. HOLD may use the
   approximate existing exposure or null if exact targeting is not justified.
   BUY and ADD MUST use a positive target that is large enough to represent at
   least one additional whole share using the supplied portfolio total and
   current market snapshot. Never return BUY/ADD with 0%, a null target, or a
   target that intentionally rounds to zero shares. If even one share would be
   inappropriate or violate the supplied risk policy, choose WATCH/IGNORE for a
   non-held name or HOLD for an existing holding instead.
10. Read `deterministic_risk_policy` before choosing exposure. Do not knowingly
    propose sizing that obviously violates the supplied max-order, position,
    invested-capital, cash-reserve, new-position, or liquidity limits. If a
    smaller starter allocation is appropriate, choose a compliant target with
    enough numerical precision to survive whole-share sizing. Do not force a
    trade merely to fit a limit.
11. Confidence expresses confidence in the ACTION given the evidence, not a
    probability of making money.
12. Keep reasoning decision-focused and grounded in evidence. If live research
    changes or contradicts upstream research, explain that in `what_changed`.
13. `thesis_update` should capture the current investable thesis when useful.
    WATCH may carry a thesis if there is a genuine monitored setup. IGNORE
    should normally use null for thesis fields. `thesis_invalidation` should
    state what would invalidate a meaningful thesis; otherwise null.
14. Think across the whole portfolio as well as one symbol at a time. Cash is a
    valid position. You are not required to buy any minimum number of names.
15. Persistent WATCHLIST relationships are intentional monitored interests. Re-
    evaluate them on every run using fresh evidence; they are not automatic BUYs
    and may remain WATCH, become BUY, or become IGNORE when no longer useful.

CEREBRO CONTEXT:
{json.dumps(context, ensure_ascii=False, default=str)}

Return only the requested structured result.
""".strip()

    def _validate(self, context, result):
        candidates = context.get("candidates") or []
        allowed_symbols = [
            str(item.get("symbol")).upper()
            for item in candidates
            if item.get("symbol")
        ]
        allowed_set = set(allowed_symbols)

        held_symbols = {
            str(item.get("symbol")).upper()
            for item in (context.get("portfolio", {}).get("positions") or [])
            if item.get("symbol")
        }

        decisions = result.get("decisions") or []
        seen = set()

        for decision in decisions:
            symbol = str(decision.get("symbol") or "").upper()
            decision["symbol"] = symbol
            action = str(decision.get("action") or "").upper()
            decision["action"] = action

            if symbol not in allowed_set:
                raise RuntimeError(f"Decision model returned out-of-context symbol: {symbol}")
            if symbol in seen:
                raise RuntimeError(f"Decision model returned duplicate symbol: {symbol}")
            seen.add(symbol)

            allowed_actions = (
                {"ADD", "HOLD", "REDUCE", "SELL"}
                if symbol in held_symbols
                else {"BUY", "WATCH", "IGNORE"}
            )
            if action not in allowed_actions:
                raise RuntimeError(
                    f"Invalid action {action} for {symbol}; allowed: {sorted(allowed_actions)}"
                )
            if action in {"WATCH", "IGNORE"}:
                decision["desired_exposure_pct"] = None

        missing = [symbol for symbol in allowed_symbols if symbol not in seen]
        if missing:
            raise RuntimeError("Decision model omitted candidate symbols: " + ", ".join(missing))
        if len(decisions) != len(allowed_symbols):
            raise RuntimeError("Decision count does not match candidate count")
        return result

    def _request_with_retry(
        self,
        *,
        model,
        reasoning_effort,
        prompt,
        web_search_enabled,
        search_context_size,
        retry_callback=None,
        request_callback=None,
    ):
        """Run the single portfolio-decision request with rate-limit recovery."""
        max_attempts = 4
        kwargs = {
            "model": model,
            "reasoning": {"effort": reasoning_effort},
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "cerebro_portfolio_decisions",
                    "strict": True,
                    "schema": DECISION_SCHEMA,
                }
            },
        }
        if web_search_enabled:
            kwargs.update({
                "tools": [{
                    "type": "web_search",
                    "search_context_size": search_context_size,
                }],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
            })
        # Capture the same body once. Retries reuse it even if settings change.
        if request_callback:
            request_callback(deepcopy(kwargs))
        for attempt in range(1, max_attempts + 1):
            try:
                return self._client().responses.create(**kwargs)
            except Exception as exc:
                if attempt >= max_attempts or not is_retryable_openai_error(exc):
                    raise

                delay, retry_source, provider_delay = retry_delay(
                    exc,
                    attempt=attempt,
                    base_delay=2.0,
                    safety_seconds=1.0,
                )
                if retry_callback:
                    retry_callback(
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_seconds=round(delay, 3),
                        provider_retry_after_seconds=(
                            round(provider_delay, 3)
                            if provider_delay is not None else None
                        ),
                        retry_source=retry_source,
                        error=str(exc),
                    )
                time.sleep(delay)
        raise RuntimeError("Decision model retry loop exhausted")

    def _web_search_usage(self, response):
        calls = 0
        sources = set()
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "web_search_call":
                continue
            calls += 1
            action = getattr(item, "action", None)
            for source in getattr(action, "sources", None) or []:
                url = getattr(source, "url", None)
                if url:
                    sources.add(str(url))
        return {"calls": calls, "source_count": len(sources)}

    def run(
        self,
        *,
        run_type="MANUAL",
        enrich_research=True,
        context=None,
        retry_callback=None,
        request_callback=None,
    ):
        if context is None:
            context = ai_run_context.build(
                run_type=run_type,
                enrich_research=enrich_research,
            )

        # This normalized copy is both the prompt's JSON and the inspector view.
        context = json.loads(json.dumps(context, ensure_ascii=False, default=str))
        candidates = context.get("candidates") or []
        if not candidates:
            raise RuntimeError("Decision context contains no candidates")

        model = str(settings.get("ai.decision.model"))
        reasoning_effort = str(settings.get("ai.decision.reasoning_effort"))
        web_search_enabled = settings.get_bool("ai.decision.web_search_enabled")
        search_context_size = str(settings.get("ai.decision.search_context_size"))

        request_snapshot = None

        def capture_request(request):
            nonlocal request_snapshot
            instructions, _, tail = request["input"].partition("\n\nCEREBRO CONTEXT:\n")
            final_instruction = tail.rsplit("\n\n", 1)[-1]
            request_snapshot = {
                "schema_version": 1,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "request": request,
                "context": deepcopy(context),
                "instructions": instructions + "\n\n" + final_instruction,
            }
            if request_callback:
                request_callback(deepcopy(request_snapshot))

        response = self._request_with_retry(
            model=model,
            reasoning_effort=reasoning_effort,
            prompt=self._prompt(context, web_search_enabled=web_search_enabled),
            web_search_enabled=web_search_enabled,
            search_context_size=search_context_size,
            retry_callback=retry_callback,
            request_callback=capture_request,
        )

        result = self._validate(context, json.loads(response.output_text))
        web_usage = self._web_search_usage(response)

        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "run_type": str(run_type).upper(),
            "candidate_count": len(candidates),
            "decision_web_research": {
                "enabled": web_search_enabled,
                "search_context_size": search_context_size if web_search_enabled else None,
                **web_usage,
            },
            "context": context,
            "request_snapshot": request_snapshot,
            "decision": result,
            "execution": {
                "attempted": False,
                "status": "INTENTS_ONLY",
                "message": (
                    "No orders were placed. Decisions must pass deterministic "
                    "proposal and risk evaluation before execution."
                ),
            },
        }


ai_decision = AIDecisionEngine()
