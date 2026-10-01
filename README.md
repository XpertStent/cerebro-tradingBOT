# Cerebro / Moomoo OpenD Trading Stack

Cerebro is a Docker-based US-equity research and PAPER-trading control system built around Moomoo OpenD. It combines market discovery, historical quant ranking, clustered AI research/news, structured portfolio decisions, deterministic risk controls, persistent AI memory, order management, and a React control UI.

> **Execution boundary:** this build is PAPER / simulated trading only. Live brokerage execution is deliberately blocked until a separate live-trading phase is implemented and validated.

## Services

| Service | Purpose | Host access |
| --- | --- | --- |
| `opend` | Moomoo OpenD gateway | API 11111 internally |
| `login-ui` | OpenD login/status helper | `:6789` |
| `cerebro` | FastAPI backend, quant, AI, risk, memory and PAPER execution | `:7000` through the shared OpenD network namespace |
| `cerebroui` | React control UI | `:7100` |

Persistent state lives in Docker volumes. `cerebro-data` contains SQLite state, latest quant/AI artifacts, market/history caches and the AI research cache.

## Manual AI workflow

**CerebroUI → Strategies → Run AI Decision** runs the full pipeline:

1. Refresh the eligible US equity universe.
2. Run independent discovery screens.
3. Perform historical analysis and multi-factor ranking.
4. Persist the fresh quant result.
5. Build decision context from current PAPER account state, held positions, pending orders, watchlist, quant candidates, fresh market snapshots, AI memory and current deterministic risk settings.
6. Research holdings/candidates using the configured **Research / News Model** in clustered web-research requests.
7. Run one structured **Decision-Making Model** request across the complete portfolio context. By default, the final decision model also has its own live web-search tool so it can independently verify or augment the upstream research before deciding.
8. Validate the returned decisions and persist decision/thesis memory.
9. Convert actionable decisions into deterministic whole-share proposals.
10. Apply deterministic portfolio/risk controls.
11. With auto-execution OFF (default), wait for per-decision approval/rejection. With auto-execution ON, submit only risk-valid PAPER orders.
12. Re-price and re-run risk checks immediately before every broker submission.

The AI does not directly control the broker. Sizing, duplicate-order prevention, execution mode and final risk validation remain deterministic Cerebro code.

## AI actions

The decision model can return:

- `BUY` — open a new position
- `ADD` — increase an existing holding
- `HOLD` — retain an existing holding
- `REDUCE` — partially reduce an existing holding
- `SELL` — exit an existing holding
- `WATCH` — no order now, but keep the non-held symbol under consideration
- `IGNORE` — dismiss the non-held symbol for the current run

Held symbols are constrained to `ADD / HOLD / REDUCE / SELL`. Non-held symbols are constrained to `BUY / WATCH / IGNORE`.

The prompt explicitly allows independent investment analysis using quant signals, market snapshots, clustered research/news, portfolio state, memory, deterministic risk policy and, when enabled, the decision model's own live web verification. Missing upstream research is not treated as an automatic WATCH instruction.

## Clustered research/news and rate limits

Research/news is batched dynamically instead of sending one OpenAI request per symbol. **Settings → AI & Models → Research → Parallel Research Clusters** controls the number of concurrent balanced research requests.

Example: 30 research symbols with 4 clusters are split approximately `8 + 8 + 7 + 7`. Cached research is removed before clustering, so repeat runs may require fewer API calls.

Transient OpenAI failures are retried. For a provider response such as `Please try again in 425ms`, Cerebro waits the provider-specified delay **plus a 1-second safety buffer** before retrying. `Retry-After` headers are preferred when present. If no provider delay is available, Cerebro falls back to exponential backoff with jitter for rate-limit, timeout, connection and retryable 5xx failures.

The final decision request uses the same retry mechanism, so a TPM/RPM burst during portfolio analysis does not immediately fail the entire run.

### Decision-model web verification

The final decision model has separate runtime settings under **AI & Models → Decision Model**:

- **Decision Model Web Research** — default ON
- **Decision Web Search Context Size** — low / medium / high

This is intentionally separate from the clustered research stage. The upstream research model gathers structured company/news evidence, while the final decision model may independently verify recent material facts, investigate failed research gaps, or resolve conflicting evidence before returning the final portfolio decisions.

The Strategies page reports whether final decision web verification is active and, after completion, how many decision-model web-search calls / unique observed sources were used.

## Decision and approval behaviour

`execution.auto_execute` / **Authorize AI Auto-Execution** defaults to OFF.

When OFF, each actionable risk-approved proposal has its own:

- **Approve & Execute this order**
- **Reject this decision**

Resolving one decision does not resolve the others. The page also provides **Approve All Remaining** and **Reject All Remaining** conveniences; these still process the remaining proposals individually so each approval receives the same fresh broker/price/risk validation.

When auto-execution is ON, approval controls are omitted for that run because risk-approved PAPER proposals are executed immediately. Live execution remains blocked.

## Deterministic risk context

The model is informed about the current execution policy so it can propose realistic allocations, including trading/risk state, PAPER-only mode, maximum order value, maximum position percentage, maximum invested percentage, minimum cash reserve, maximum new positions per run, liquidity limits, default order type and auto-execution state.

These values are context, not authority. Cerebro independently enforces the risk engine after the model response and again immediately before broker submission.

## CerebroUI

The UI is organized around Dashboard, Markets, Watchlist, Strategies, Orders, Portfolio, Activity / Logs and Settings.

Navigation uses hash routes such as `#/strategies` and `#/orders`, so browser refresh, Back and Forward preserve the selected module instead of returning to Dashboard. Cross-module links use the same navigation layer; order/portfolio/watchlist/AI symbols can open directly in Markets.

Reusable collapsible sections and bounded scroll regions are used for large datasets. Nested result panes deliberately use normal scroll chaining: when an inner list reaches its top or bottom, mouse-wheel scrolling continues on the main page instead of trapping the pointer inside that section.

### Strategies research inspection

**Live Research Status** is an in-place inspector, not a navigation shortcut. Clicking a research symbol keeps you on Strategies and shows the stored result, retry state, cache status, or exact error payload underneath the status grid. Research-error cards also expand in place.

Large quant and AI-decision lists remain internally scrollable, but scroll control hands back to the page at their boundaries.

### Watchlist

The Watchlist supports live ticker/company suggestions, explicit Search button and Enter-to-search, manual Add / Remove, direct Markets navigation, batched live snapshots, current traded price/change/% change, graceful quote failures and short-lived server-side search caching.

### Activity / Logs

The Activity page combines the persistent SQLite audit trail with live events from an active AI workflow. It supports:

- text search
- category and level filters
- automatic refresh
- events collapsed by default
- individual event expansion
- **Expand all / Collapse all** controls
- raw structured event details
- symbol/order metadata
- deep links back to Markets or Orders

Live quant/research/model/risk workflow events appear while a run is in progress; durable audit entries remain stored separately in SQLite for important workflow/order/watchlist actions.

### Orders and Portfolio

Orders supports manual symbol search, risk preview, PAPER execution, pending-order cancellation and direct symbol navigation. Portfolio positions also link directly to the Markets detail/chart page.

## Stored results and testing controls

Strategies provides separate controls for:

- **Clear Quant** — remove the latest quant artifact
- **Clear AI Result** — remove the latest displayed/persisted AI result
- **Clear All AI History** — destructive test reset for AI runs, decisions, outcomes and thesis memory

The all-history reset intentionally does not delete broker orders, settings, watchlist, activity logs, market-history caches or quant artifacts.

A manual AI run always performs a fresh quant pass before the AI stages.

## Settings

Settings are SQLite-backed and most behaviour is runtime configurable without rebuilding containers. Important groups include discovery limits, quant weights, data-quality filters, research model, **Parallel Research Clusters**, decision model/reasoning effort, **Decision Model Web Research**, AI context limits, deterministic portfolio/risk limits and execution controls.

The OpenAI API key is treated as a secret and is not returned to the browser.

## Start / redeploy

```bash
docker compose up -d --build
```

For backend/UI-only rebuilds:

```bash
docker compose build cerebro cerebroui
docker compose up -d cerebro cerebroui
```

For Portainer GitOps testing of this feature branch:

```text
Repository: https://github.com/XpertStent/moomoo-opend.git
Reference:  refs/heads/feature/ai-decision-engine
```

## Useful API endpoints

### System

- `GET /health`
- `GET /system/status`

### Market / watchlist

- `GET /market/search`
- `GET /market/snapshots`
- `GET /market/{symbol}`
- `GET /market/{symbol}/candles`
- `GET /watchlist/`
- `POST /watchlist/`
- `DELETE /watchlist/{symbol}`

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
- `DELETE /ai/decision/history`
- `POST /ai/decision/{run_id}/proposal/{decision_id}/approve`
- `POST /ai/decision/{run_id}/proposal/{decision_id}/reject`

Legacy run-level approve/reject endpoints remain available for compatibility. CerebroUI bulk controls intentionally resolve proposals through the individual proposal endpoints.

### Orders

- `GET /orders/`
- `POST /orders/preview`
- `POST /orders/execute`
- `DELETE /orders/{order_id}`

### Activity / Settings

- `GET /activity/`
- `GET /settings`
- `PUT /settings`
- `POST /settings/reset`

FastAPI documentation is available from Cerebro at `/docs`.

## Validation

GitHub Actions validates feature pushes by compiling all Python under `cerebro/app`, installing CerebroUI dependencies and building the React production bundle. CI verifies syntax/build integrity; the final branch still needs a real local OpenD PAPER smoke test because CI cannot exercise a logged-in broker or external OpenAI request.

## Safety boundary

This branch is intended for simulated trading. UI actions, model output and API callers cannot intentionally bypass the deterministic PAPER-only execution boundary. Live trading requires separate account selection, unlock/safeguards and dedicated validation before it should be enabled.
