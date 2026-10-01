# Cerebro / Moomoo OpenD Trading Stack

Cerebro is a Docker-based US-equity trading research and paper-execution system built around Moomoo OpenD. It combines local market discovery, historical multi-factor quant ranking, AI web research, structured AI portfolio decisions, deterministic risk controls, persistent decision memory, and a React control interface.

> **Current execution scope:** paper trading only. Live broker execution is intentionally disabled until a separate live-trading phase is implemented and validated.

## Services

| Service | Purpose | Host access |
| --- | --- | --- |
| `opend` | Moomoo OpenD gateway | shared with Cerebro; API on 11111 internally |
| `login-ui` | OpenD login/status helper | `:6789` |
| `cerebro` | FastAPI backend, quant, AI, risk, execution, memory | shares OpenD network namespace; host `:7000` through OpenD namespace |
| `cerebroui` | React control UI | `:7100` |

Persistent state is stored in Docker volumes:

- `opend-state` — OpenD state
- `cerebro-data` — SQLite database, market/history cache, latest quant result, latest AI decision result, AI research cache

## Core workflow

A manual AI decision run from **CerebroUI → Strategies** performs the full pipeline:

1. Refresh the eligible US listing universe.
2. Run independent snapshot discovery screens.
3. Deep-analyse the configured candidate pool using historical market data.
4. Rank candidates with the configured multi-factor quant model.
5. Persist the latest quant result.
6. Build portfolio context from current paper positions, pending orders, watchlist, quant candidates, AI memory, and the currently configured deterministic risk limits.
7. Run AI web research for relevant holdings / quant candidates. Transient rate-limit, timeout, connection, and 5xx failures are retried with exponential backoff and jitter before research is marked failed.
8. Send the structured context to the configured decision model.
9. Validate that the model returns exactly one allowed action for every candidate.
10. Persist decisions and thesis updates.
11. Convert actionable intents into deterministic whole-share order proposals.
12. Run deterministic risk checks.
13. Either:
    - wait for an **individual Approve / Reject decision on each actionable proposal** in CerebroUI (default), or
    - automatically submit risk-approved PAPER orders when **Authorize AI Auto-Execution** is enabled in Settings.

AI never talks directly to the broker. Order sizing, fresh pre-execution validation, and risk approval remain deterministic Cerebro code.

## Live workflow telemetry

The Strategies page polls workflow status while a manual run is active and shows operational progress for:

- quant stage, symbol, elapsed time and completion percentage
- parallel research completion counts
- research-ready and research-error counts
- symbols as research workers finish
- number of research workers still in flight
- research retry state for transient/rate-limit failures
- decision-model request state and elapsed time
- deterministic risk / proposal stage
- an event stream covering quant, research, model, risk and approval stages

The UI does **not** expose private model chain-of-thought. During the decision-model stage it shows that the request is active, how long it has been running, and the final structured reasoning/output when complete.

Quant progress is explicitly set to 100% when historical analysis finishes. The internal 99% cap is used only while a quant job is still actively processing.

## AI actions

The decision model can return:

- `BUY` — open a new position
- `ADD` — increase an existing holding
- `HOLD` — keep an existing holding
- `REDUCE` — reduce an existing holding without fully exiting
- `SELL` — fully exit a holding
- `WATCH` — no order now, but the non-held candidate remains interesting enough to monitor for a future trigger, better entry, event resolution, or stronger evidence
- `IGNORE` — no order and no monitoring thesis is warranted for that non-held candidate in the current run

Held symbols are constrained to `ADD / HOLD / REDUCE / SELL`; non-held symbols are constrained to `BUY / WATCH / IGNORE`.

The decision prompt explicitly tells the model to perform independent investment reasoning across quant signals, structured research, portfolio state, memory, uncertainty, and risk limits. Missing web research is not by itself a command to WATCH: the model must decide whether remaining evidence supports BUY, WATCH, or IGNORE without inventing facts.

## Risk-aware AI context

The decision context contains the deterministic execution policy, including:

- trading/risk engine state
- current PAPER execution boundary
- maximum order value
- maximum single-position percentage
- maximum invested-capital percentage
- minimum cash reserve percentage
- maximum new positions per run
- maximum order size relative to 60-day median turnover
- current default order type and auto-execution state

This does not give the AI authority over risk controls. It lets the model choose realistic target exposure instead of knowingly requesting sizing that the deterministic engine will reject. Every actionable proposal is still independently evaluated by Cerebro after the model responds, and risk is checked again with fresh broker/price state immediately before execution.

## Quant discovery and ranking

Discovery screens are independent and each has its own configurable Top-N:

- Daily Momentum
- Volume Surge
- Turnover Rate
- Liquidity
- Near 52-Week High

The deduplicated discovery union is then historically analysed and ranked with these configurable final factors:

- Momentum
- Trend
- Relative Strength
- Breakout
- Volume
- Volatility Quality
- Overextension Quality

The default final factor weights remain 22 / 22 / 18 / 12 / 10 / 8 / 8 percent and must total 100%.

## Settings

Cerebro uses a persistent SQLite-backed Settings registry. Most behaviour can be changed from **CerebroUI → Settings** without rebuilding containers.

Important sections include:

- General / trading mode
- Independent discovery screen limits
- Universe and liquidity filters
- Final quant factor weights
- Advanced factor composition
- Data-quality and discontinuity thresholds
- AI research model and research concurrency
- AI decision model and reasoning effort
- AI context / memory limits
- Portfolio and risk limits
- Execution controls
- Automation placeholders for future scheduled cycles

The OpenAI API key is treated as a secret and is never returned to the browser.

### AI model separation

Cerebro intentionally keeps these separate:

- **OpenAI API Key**
- **Research / News Model**
- **Decision-Making Model**

Changing the research model does not change the final portfolio decision model.

## Manual approval vs auto-execution

`execution.auto_execute` / **Authorize AI Auto-Execution** defaults to `OFF`.

### OFF — default

After a completed AI run, CerebroUI shows the full decision set, reasoning, research status, target exposure, deterministic order proposal, and risk checks.

Every risk-approved actionable proposal has its own controls:

- **Approve & Execute this order** — approves and submits only that proposal after a fresh deterministic risk check.
- **Reject this decision** — rejects only that proposal and submits no order for it.

Approving or rejecting one symbol never resolves another symbol's proposal. WATCH, IGNORE and HOLD decisions require no broker order. Risk-blocked proposals cannot be manually forced through the UI.

### ON

Risk-approved PAPER proposals are submitted immediately after the AI decision completes. The decision summary remains visible, but manual Approve / Reject controls are not shown because execution has already occurred.

## CerebroUI presentation

Reusable collapsible sections are used across Dashboard, Strategies, Orders, Portfolio, Watchlist and Activity / Logs. Settings uses collapsible subsection groups.

Large result sets use bounded scroll regions so quant rankings, AI decisions, activity history, order history and positions do not force the entire page to become excessively tall.

Security links in quant results, research status, orders and positions open the corresponding symbol directly in **Markets**, reusing the same quote/chart detail view as a manual market search.

Each AI decision is individually collapsible and shows its research status. READY research displays retained source count/cache state; failed research displays the actual returned error to make quota/rate-limit problems visible instead of silently appearing as “research unavailable.”

## Order management

The Orders page supports:

- manual order preview
- deterministic risk checks
- PAPER order execution
- live order-history refresh
- cancellation of non-terminal pending PAPER orders
- **View** navigation from any order to the security's Markets detail page

Filled, cancelled, failed, disabled, or deleted orders are treated as terminal and cannot be cancelled again.

## Stored results and test runs

The Strategies page provides separate controls to clear:

- the latest persisted quant result
- the latest persisted AI decision result
- **all persistent AI decision history and thesis memory** for explicit test resets

The **Clear All AI History** control requires two browser confirmations. It deletes AI runs, decisions, decision outcomes and thesis history, plus the latest AI decision artifact. It does **not** delete broker orders, settings, watchlist, activity logs, cached market history, quant artifacts or research cache.

A fresh **Run AI Decision** always starts a new quant run before research and decision generation.

## AI memory

SQLite stores:

- AI runs / decisions
- execution status and broker order IDs
- active and historical theses
- thesis invalidation text
- recent risk / user rejections
- future decision-outcome evaluation records

The thesis schema allows historical closed theses while enforcing only one ACTIVE thesis per symbol.

## Risk controls

Current deterministic checks include:

- risk engine enabled
- trading execution enabled
- PAPER-only execution boundary
- valid order quantity
- maximum order value
- maximum single-position percentage
- maximum invested-capital percentage
- minimum cash reserve percentage
- maximum number of new positions per AI run
- maximum order value relative to 60-day median turnover when available

Risk-approved AI proposals are re-priced and re-evaluated against fresh account, position, pending-order, and market state immediately before order submission.

## Environment

At minimum, configure the OpenD credentials required by the container image and an OpenAI API key for AI features.

Example `.env` entries:

```env
OPENAI_API_KEY=...
OPENAI_RESEARCH_MODEL=gpt-5.6-luna
AI_RESEARCH_MAX_WORKERS=12
```

Do not commit `.env` or API keys.

## Start / rebuild

```bash
docker compose up -d --build
```

For normal backend/UI development rebuilds:

```bash
docker compose build cerebro cerebroui
docker compose up -d cerebro cerebroui
```

## Useful endpoints

### System

- `GET /health`
- `GET /system/status`

### Quant

- `POST /quant/run`
- `GET /quant/progress/{run_id}`
- `GET /quant/result/{run_id}`
- `GET /quant/latest`
- `DELETE /quant/latest`

### AI decision engine

- `POST /ai/decision/run`
- `GET /ai/decision/progress/{run_id}`
- `GET /ai/decision/result/{run_id}`
- `GET /ai/decision/latest`
- `DELETE /ai/decision/latest`
- `DELETE /ai/decision/history` — destructive test-only AI memory reset
- `POST /ai/decision/{run_id}/proposal/{decision_id}/approve`
- `POST /ai/decision/{run_id}/proposal/{decision_id}/reject`
- legacy batch approve/reject endpoints remain for compatibility but CerebroUI does not use them

### Orders

- `GET /orders/`
- `POST /orders/preview`
- `POST /orders/execute`
- `DELETE /orders/{order_id}`

### Settings

- `GET /settings`
- `PUT /settings`
- `POST /settings/reset`

FastAPI documentation is available from the Cerebro service at `/docs`.

## Validation

GitHub Actions validates every `main` and `feature/**` push by:

1. compiling all Python under `cerebro/app`
2. installing CerebroUI dependencies
3. building the React production bundle

Before merging an AI-engine change, also validate it against the real local OpenD PAPER environment because CI cannot exercise a logged-in broker session or external OpenAI calls.

## Safety boundary

This repository currently supports PAPER execution only. A UI setting, AI response, or API caller cannot intentionally bypass the deterministic risk layer to reach live brokerage execution. Live trading requires a separate implementation covering real-account selection, trade unlock, live-only safeguards, and dedicated validation.
