# Cerebro TradingBOT

Cerebro is a Docker-based US-equity research and trading application. Moomoo OpenD supplies account access and broker execution; OpenD or Alpaca supplies market data. CerebroUI provides portfolio monitoring, charts, orders, configurable risk controls and AI-assisted decisions.

## Current version

`main` now includes both PAPER and LIVE trading. Deploy `main`; the merged `feature/live-trading` branch has been deleted.

The latest code checkpoint is `checkpoint-phase6-stable`. Checkpoints use `checkpoint-phase<N>-stable`: phase 4 covers settings, phase 5 the AI decision engine, and phase 6 live trading and the market-data/workflow improvements. Tags pin their original commits; subsequent updates are on `main`.

## Deployment

In Portainer, configure the Git stack with:

- Repository: `https://github.com/XpertStent/cerebro-tradingBOT.git`
- Reference: `refs/heads/main`
- Compose file: `docker-compose.yml`

Rebuild/redeploy the stack to apply changes. Backend and UI changes require rebuilding their respective containers; refresh the browser afterward.

| Service | Purpose | Access |
| --- | --- | --- |
| `opend` | Moomoo gateway and broker connection | Internal SDK connection |
| `login-ui` | OpenD login/status helper | Port `6789` |
| `cerebro` | Backend, quant, AI, risk and execution | Port `7000`, sharing OpenD's network namespace |
| `cerebroui` | Web interface | Port `7100` |

Keep the `cerebro-data` and `opend-state` volumes when redeploying.

## Configuration and trading mode

Configure OpenAI and Alpaca credentials in **Settings → API KEYS**. Existing `OPENAI_API_KEY` environment configuration remains supported. Models and reasoning settings are separate under **AI & Models**.

Choose **Settings → General → Trading → Trading Mode**:

- **PAPER:** Moomoo's simulated account; no trade unlock required.
- **LIVE:** an eligible ACTIVE REAL account with US trading permission; broker actions require unlock.

The selected mode/account supplies portfolio balances, AI context, sizing, risk checks and order history. Changing it clears local unlock state. Existing AI proposals remain bound to their original execution account; generate a fresh run after switching.

`trading.enabled` controls whether new orders are allowed. `execution.auto_execute` controls automatic AI execution. With auto-execution off, proposals wait for manual approval; a locked LIVE account defers automatic broker execution to manual approval.

## LIVE unlock and execution

Use **Unlock Trading** in the header to select an eligible account and enter your six-digit Moomoo trading password. OpenD's account identifier can differ from the account number displayed in the mobile app.

The browser hashes the password locally with MD5, clears the input before sending the request, and sends only the hash. Neither the raw password nor the submitted hash is persisted by Cerebro. An optional `MOOMOO_TRADING_PASSWORD_MD5` environment value remains available as a fallback when the field is blank. The hash is also a credential: use HTTPS for transport.

When a broker action requires unlock, the UI opens the unlock dialog and retries that action after successful unlock. The header also allows explicit locking.

LIVE submissions require the regular US session, fresh account/price checks and deterministic risk approval. Controls include available cash, position and invested exposure, cash reserve, order limits, available sell quantity, BUY cooldown and AI slippage. Orders use whole shares and long-only positions; options and automatic short creation are unsupported.

## Orders and portfolio

**Orders → New Order** supports MARKET and LIMIT orders. LIVE mode additionally exposes STOP, STOP LIMIT and GTC; PAPER uses DAY orders. Preview refreshes the account and applies risk checks before submission.

Pending cancellable orders can be cancelled through OpenD. Cancellation requires broker confirmation and can fail if an order fills first; it does not erase the order's history. Broker order history is saved locally and refreshed every ten minutes for the active account.

Portfolio displays cash, available funds, market value, current positions and portfolio percentages. LIVE BUY capacity uses verified USD cash and cash buying power, excluding margin buying power. Position P&L and average-cost unrealized P&L are separate; total realized P&L remains unavailable without verified closed-trade history. The daily loss guard measures observed account equity change, including cash transfers.

## Market data and candles

Choose **Settings → Data & Quality → Market Data Provider**: OpenD or Alpaca. Feed, delay, adjustment, history size and quality controls are configured in the same section. Account data, security fundamentals and execution remain with OpenD.

- Charts and quant analysis share the persistent candle service. Caches are partitioned by provider, feed, adjustment, session, symbol and timeframe.
- **History Fetch Count** sets the analysis history target. Provider pagination can download more bars; quant analysis uses completed candles and rejects stale or unusable history.
- Exchange calendars account for holidays and shortened sessions. Adjusted history is refreshed at trading-date/session transitions to incorporate corporate actions.
- Alpaca requests share configurable rate limiting, retries and provider cooldown handling. Switching providers does not silently reuse another provider's data.
- Scrolling back requests and caches earlier candles. **Follow latest** refreshes the chart; **Latest** returns to the newest available bar. Chart boundaries prevent scrolling beyond available data, with exchange-time labels for intraday bars and trading-date labels for daily bars.

## AI workflow and review

**Strategies → Run AI Decision** runs:

1. Discovery and historical quant analysis, including comparison with SPY.
2. Context building from the active portfolio, watchlist, pending orders, research and saved AI memory.
3. Clustered research requests, followed by one portfolio-wide decision-model request.
4. Deterministic sizing and risk checks, then proposal approval or configured automatic execution.

The model can propose BUY, ADD, HOLD, REDUCE, SELL, WATCH or IGNORE. Application code controls sizing and broker execution.

Individual approval/rejection buttons require a second click to confirm. Bulk actions show the final pending list for confirmation. Rejected proposals leave the pending list and cannot be approved by a later Approve All. An optional rejection reason is stored with `USER_REJECTED`; policy failures use `CURRENT_SET_RISK_POLICY_BLOCKED`.

Generated decisions, reasoning, confidence, context snapshots, execution results and rejection reasons remain in AI memory. Proposed theses stay inactive until approval succeeds.

### Workflow inspection

- **Live Workflow Activity:** expand historical analysis rows in place for fetched/analysed candle counts, latest completed candle, provider/cache details, freshness and anomalies.
- **Live Research Status:** select a symbol to view its research output and sources as soon as its batch completes, including cache and error status.
- **Decision Model Input:** inspect the exact captured initial decision request, split into symbols, shared context, instructions and full request. This does not include outbound research-batch prompts or information retrieved later by decision-stage web search.
- **Decision Summary:** review the final structured decisions and proposals.

## Persistent storage

The `cerebro-data` volume mounts at `/data`:

| Location | Contents |
| --- | --- |
| `cerebro.db` | Settings/API credentials, account selection, activity, broker history and AI memory |
| `market_history.db` | Provider-separated candle cache and refresh metadata |
| `latest_quant.json`, `latest_ai_decision.json`, `latest_decision_input.json` | Latest quant result, completed AI result and captured initial decision input |
| `ai_research/` | Cached per-symbol research |

OpenD login state is stored separately in `opend-state`. Keep real credentials and account figures out of source control and documentation.
