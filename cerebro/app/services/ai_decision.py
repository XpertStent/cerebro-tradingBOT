import json
from datetime import datetime, timezone

from openai import OpenAI

from app.services.ai_run_context import ai_run_context
from app.services.settings import settings


DECISION_SCHEMA_VERSION = 2

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "portfolio_summary": {
            "type": "string",
        },
        "market_summary": {
            "type": "string",
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "BUY",
                            "ADD",
                            "HOLD",
                            "REDUCE",
                            "SELL",
                            "WATCH",
                            "IGNORE",
                        ],
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "reasoning": {
                        "type": "string",
                    },
                    "what_changed": {
                        "type": ["string", "null"],
                    },
                    "thesis_update": {
                        "type": ["string", "null"],
                    },
                    "thesis_invalidation": {
                        "type": ["string", "null"],
                    },
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
    "required": [
        "portfolio_summary",
        "market_summary",
        "decisions",
    ],
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

    def _prompt(self, context):
        return f"""
You are the portfolio decision layer for Cerebro, an automated US-equity
trading system.

You receive deterministic portfolio state, broker state, current holdings,
pending orders, the latest quant candidate set, structured company research,
prior theses, recent decisions, rejections, current market state, and the
CURRENT DETERMINISTIC RISK POLICY that any proposed order must pass.

Your job is to produce PORTFOLIO INTENTS ONLY. You never place orders and you
never bypass deterministic risk controls.

You are explicitly expected to perform independent investment analysis and
reasoning on each supplied candidate. Synthesize the evidence; compare signals,
quality, uncertainty, portfolio fit, and risk. Do not merely restate quant flags
or mechanically copy prior decisions. You may reach your own conclusion from
the supplied evidence, but do not invent external facts that are absent from
the context.

Allowed actions:
- BUY: initiate a new position in a symbol not currently held.
- ADD: increase an existing holding.
- HOLD: keep an existing holding broadly unchanged.
- REDUCE: decrease an existing holding without fully exiting.
- SELL: fully exit an existing holding.
- WATCH: no order now, but the candidate remains sufficiently interesting to
  monitor for a future trigger, better entry, event resolution, or stronger
  evidence.
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
   portfolio concentration, available cash, existing thesis, and uncertainty
   all matter.
7. A price discontinuity marked as a real event is not automatically bullish
   or bearish. Use the supplied research assessment.
8. Missing research is NOT by itself a command to WATCH. Use the quant data,
   event-review state, portfolio context, memory, and any available research to
   reason independently. If a candidate remains interesting but needs more
   evidence, WATCH is appropriate. If it is not worth monitoring, use IGNORE.
   If supplied evidence is already strong enough and risks are understood, a
   BUY may still be justified without web research.
9. `desired_exposure_pct` is a target percent of total portfolio value after
   the proposed action. Use null for WATCH and IGNORE. HOLD may use the
   approximate existing exposure or null if exact targeting is not justified.
10. Read `deterministic_risk_policy` before choosing exposure. Do not knowingly
    propose sizing that obviously violates the supplied max-order, position,
    invested-capital, cash-reserve, new-position, or liquidity limits. If a
    smaller starter allocation is appropriate, choose a compliant target. Do
    not force a trade merely to fit a limit.
11. Confidence expresses confidence in the ACTION given the supplied evidence,
    not a probability of making money.
12. Keep reasoning decision-focused and grounded in supplied context.
13. `thesis_update` should capture the current investable thesis when useful.
    WATCH may carry a thesis if there is a genuine monitored setup. IGNORE
    should normally use null for thesis fields. `thesis_invalidation` should
    state what would invalidate a meaningful thesis; otherwise null.
14. Think across the whole portfolio as well as one symbol at a time. Cash is a
    valid position. You are not required to buy any minimum number of names.

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
            for item in (
                context.get("portfolio", {}).get("positions")
                or []
            )
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
                raise RuntimeError(
                    f"Decision model returned out-of-context symbol: {symbol}"
                )

            if symbol in seen:
                raise RuntimeError(
                    f"Decision model returned duplicate symbol: {symbol}"
                )
            seen.add(symbol)

            if symbol in held_symbols:
                allowed_actions = {"ADD", "HOLD", "REDUCE", "SELL"}
            else:
                allowed_actions = {"BUY", "WATCH", "IGNORE"}

            if action not in allowed_actions:
                raise RuntimeError(
                    f"Invalid action {action} for {symbol}; allowed: "
                    f"{sorted(allowed_actions)}"
                )

            if action in {"WATCH", "IGNORE"}:
                decision["desired_exposure_pct"] = None

        missing = [symbol for symbol in allowed_symbols if symbol not in seen]
        if missing:
            raise RuntimeError(
                "Decision model omitted candidate symbols: "
                + ", ".join(missing)
            )

        if len(decisions) != len(allowed_symbols):
            raise RuntimeError(
                "Decision count does not match candidate count"
            )

        return result

    def run(
        self,
        *,
        run_type="MANUAL",
        enrich_research=True,
        context=None,
    ):
        if context is None:
            context = ai_run_context.build(
                run_type=run_type,
                enrich_research=enrich_research,
            )

        candidates = context.get("candidates") or []
        if not candidates:
            raise RuntimeError(
                "Decision context contains no candidates"
            )

        model = str(settings.get("ai.decision.model"))
        reasoning_effort = str(
            settings.get("ai.decision.reasoning_effort")
        )

        response = self._client().responses.create(
            model=model,
            reasoning={
                "effort": reasoning_effort,
            },
            input=self._prompt(context),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "cerebro_portfolio_decisions",
                    "strict": True,
                    "schema": DECISION_SCHEMA,
                }
            },
        )

        result = json.loads(response.output_text)
        result = self._validate(context, result)

        return {
            "schema_version": DECISION_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "run_type": str(run_type).upper(),
            "candidate_count": len(candidates),
            "context": context,
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
