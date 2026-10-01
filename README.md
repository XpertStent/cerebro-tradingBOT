# Cerebro TradingBOT

Cerebro is a Docker-based US-equity research and trading control stack built around Moomoo OpenD. It combines market discovery, historical quant ranking, clustered AI research/news, structured portfolio decisions, deterministic risk controls, persistent AI memory, order management, portfolio monitoring, activity auditing, and a React control UI.

## Branch policy

`main` is the stable PAPER-only checkpoint and is intentionally left untouched during LIVE-trading development.

`feature/live-trading` is the only active development branch for the LIVE implementation. Deploy this branch when testing the functionality documented below.

## Execution environments

Cerebro has two broker execution environments on `feature/live-trading`:

- **PAPER** — uses the Moomoo simulated account and does not require trade unlock.
- **LIVE** — uses an explicitly selected ACTIVE REAL account with US trading permission and requires OpenD trade unlock before broker actions.

Changing the mode changes the account used by Portfolio, Orders, AI decision context, deterministic sizing, risk checks, order history, cancellation and execution. PAPER and LIVE balances are never mixed.

## Services

| Service | Purpose | Host access |
| --- | --- | --- |
| `opend` | Moomoo OpenD gateway | API `11111` internally |
| `login-ui` | OpenD login/status helper | `:6789` |
| `cerebro` | FastAPI backend, quant, AI, risk, memory and PAPER/LIVE execution | `:7000` through the shared OpenD network namespace |
| `cerebroui` | React control UI | `:7100` |

Persistent state lives in Docker volumes. `cerebro-data` contains SQLite state, latest quant/AI artifacts, market/history caches, research cache, activity history, settings and the selected LIVE account id. The trade-unlock credential is **not** stored in SQLite.

## LIVE account discovery

Cerebro discovers Moomoo trade accounts through OpenD and separates SIMULATE from REAL accounts. LIVE selection is restricted to accounts that are:

1. REAL,
2. ACTIVE, and
3. authorized for the US market.

The broker/security-firm is discovered per account instead of assuming one hard-coded regional firm. The implementation checks security-firm values exposed by the installed Moomoo API package, including US and Australian variants when supported.

If exactly one eligible LIVE account exists, Cerebro can select it automatically. If several are available, the operator must choose one in the **Unlock Trading** control. The selected LIVE account id is persisted so a restart does not silently switch accounts.

## LIVE trade unlock

The CerebroUI header displays a persistent execution badge:

- `PAPER` in simulated mode,
- `LIVE TRADING` in real-money mode.

When LIVE mode is active, the top-right **Unlock Trading** button is visible throughout the application. The dialog lets the operator choose the eligible REAL account and asks the backend to unlock OpenD.

For security, the browser does not collect or store the raw Moomoo transaction credential. Configure the lowercase MD5 form on the `cerebro` container as:

```text
MOOMOO_TRADING_PASSWORD_MD5=<your-md5-value>
```

The value is read only from the backend container environment and passed to OpenD for unlock. Do not commit it to this repository. `.env` is ignored by Git.

The UI reports when the backend unlock credential has not been configured and disables the final unlock action until it is available.

A broker action that encounters a locked OpenD session automatically pauses in the UI, opens the same unlock dialog, and retries the original request after a successful unlock. This covers manual order placement, order cancellation and AI broker execution. WATCH decisions do not require broker unlock because they only update Cerebro's monitored securities.

The header can explicitly lock LIVE trading again.

## Portainer deployment

Point the Portainer Git stack at:

```text
https://github.com/XpertStent/cerebro-tradingBOT.git
```

and use:

```text
refs/heads/feature/live-trading
```

For LIVE testing, add this environment variable to the stack/Portainer environment without placing the value in Git:

```text
MOOMOO_TRADING_PASSWORD_MD5=<value>
```

Then redeploy/rebuild the stack. Existing OpenAI variables continue to work as before.

## Trading mode

Use **Settings → General → Trading → Trading Mode** to choose `paper` or `live`.

`trading.enabled` remains the master execution kill switch. If it is OFF, deterministic risk blocks new orders in either environment.

Switching the execution mode clears broker/account caches and resets Cerebro's local unlock state. This prevents an unlock state from being carried across an environment change.

## Why the smaller LIVE account behaves differently from the $1M PAPER account

The simulated account can be much larger than the real account, so Cerebro does not reuse the PAPER account's nominal dollar sizing.

AI sizing is expressed as a percentage of the **currently selected account's actual total value**. A 10% target is therefore calculated from the REAL account when LIVE is active, not from the simulated portfolio.

The deterministic risk engine also scales BUY capacity to the active account. The effective maximum BUY order is the lower of:

```text
configured risk.max_order_value
```

and:

```text
current portfolio value × risk.max_position_pct
```

This means a `$1,000` absolute PAPER-era ceiling cannot automatically force a `$1,000` order into a small real account.

LIVE/PAPER risk evaluation checks:

- positive whole-share quantity,
- available funds,
- maximum single-position percentage,
- maximum invested percentage,
- minimum cash reserve percentage,
- maximum order / median turnover where research data is available,
- long-only SELL quantity against available shares,
- broker-reported realized-P&L loss guard when that value is available,
- duplicate pending-order prevention in the AI path,
- maximum new positions per AI run.

Cerebro continues to execute whole shares. If an explicit AI BUY/ADD target rounds below one whole share, one-share normalization can propose one share, but that share still must pass every current-account risk check. On a small LIVE account, an expensive one-share position can therefore be blocked automatically.

## Additional LIVE-only execution guards

The first LIVE implementation intentionally starts more conservatively than the PAPER environment.

### Regular US session only

LIVE broker submissions are allowed only when Moomoo reports the US security in the regular `AFTERNOON` market state, which corresponds to the normal US continuous session. Pre-market, after-hours and overnight execution are deliberately blocked for this first LIVE release.

The market state is checked during manual preview/execution and again immediately before AI broker submission. If Cerebro cannot verify the market state, LIVE execution fails closed.

### Symbol BUY cooldown

`execution.cooldown_minutes` is now active for LIVE BUY orders. Cerebro checks the persistent Activity history for a recent LIVE Cerebro execution in the same symbol and blocks another BUY until the cooldown expires.

SELL/REDUCE exits are not blocked by this cooldown.

### AI slippage guard

`execution.max_slippage_pct` is now active for LIVE AI orders. Cerebro compares the proposal's original reference price with the fresh price obtained immediately before broker submission. If the price drift exceeds the configured limit, the AI order is blocked and the reason is written to Activity.

### Fresh server-side preview

The manual `/orders/execute` endpoint always rebuilds the preview from fresh account, position and market information before sending anything to OpenD. A direct API call therefore cannot bypass the server-side risk/session/cooldown pass.

## Manual order flow

**Orders → New Order** uses the selected execution environment.

The preview refreshes the account and positions and shows:

- PAPER/LIVE environment,
- masked selected account,
- portfolio value,
- available funds,
- estimated order value,
- projected cash,
- effective account-scaled order limit,
- every deterministic risk and LIVE safety check.

LIVE execution displays a real-money confirmation before submission. If OpenD is locked, the request pauses, the unlock dialog opens, and the original order is retried only after unlock succeeds.

Order cancellation follows the same environment and unlock rules.

## Order history

The Orders table is sourced from the active OpenD account. Every returned order contains its execution environment and account id in the backend representation, and the UI displays an explicit PAPER/LIVE environment badge.

Manual Cerebro orders use broker remarks similar to:

```text
CEREBRO:MANUAL:LIVE
CEREBRO:MANUAL:PAPER
```

AI orders use:

```text
CEREBRO:AI:<decision-id>
```

This makes Cerebro-originated orders easier to reconcile with broker history.

## Portfolio

Portfolio automatically switches to the selected PAPER or LIVE account and displays:

- environment,
- masked account id,
- security firm,
- total value,
- cash,
- available funds,
- market value,
- realized/unrealized P&L,
- current positions and available sell quantity.

The Dashboard uses the same account and does not retain the $1M simulated values after LIVE mode is selected.

## AI decision workflow

**CerebroUI → Strategies → Run AI Decision** continues to run the full pipeline:

1. Refresh the eligible US equity universe.
2. Run independent discovery screens.
3. Perform historical analysis and multi-factor ranking.
4. Persist the fresh quant result.
5. Build decision context from the **currently selected PAPER or LIVE account**, held positions, pending orders, watchlist, quant candidates, market snapshots, AI memory and deterministic risk settings.
6. Research holdings/candidates using clustered web-research requests.
7. Run one structured portfolio decision-model request with optional independent live web verification.
8. Validate and persist decisions/theses.
9. Convert actionable decisions into deterministic whole-share proposals.
10. Apply account-aware risk controls.
11. With auto-execution OFF, wait for individual/bulk approval.
12. Immediately before broker submission, refresh account/positions/price and repeat deterministic execution checks.
13. In LIVE mode also verify regular-session state, symbol BUY cooldown and proposal-to-submit slippage.
14. Submit through the selected PAPER or LIVE environment.

The AI never receives direct broker authority. Sizing and final broker execution remain deterministic application code.

### LIVE AI execution

When `execution.auto_execute` is OFF, AI proposals use the established manual-approval workflow. Approving a BUY/ADD/REDUCE/SELL in LIVE mode submits a REAL order only after fresh checks and trade unlock.

If LIVE mode is locked when a run was configured for auto-execution, Cerebro defers automatic broker execution and leaves actionable proposals for manual approval instead of failing the whole AI run or bypassing unlock.

If LIVE mode is already deliberately unlocked and `execution.auto_execute` is enabled, risk-approved deterministic AI broker actions can reach the REAL account. Keep this option OFF unless that behavior is explicitly intended.

A locked manual AI approval returns the dedicated unlock-required response. CerebroUI opens the global unlock modal and can retry that exact approval after unlock.

## AI actions

The decision model can return:

- `BUY` — open a new position
- `ADD` — increase an existing holding
- `HOLD` — retain an existing holding
- `REDUCE` — partially reduce an existing holding
- `SELL` — exit an existing holding
- `WATCH` — no broker order; retain a non-held symbol for future runs
- `IGNORE` — dismiss the non-held symbol for the current run

Held symbols are constrained to `ADD / HOLD / REDUCE / SELL`. Non-held symbols are constrained to `BUY / WATCH / IGNORE`.

## Activity and audit trail

Activity remains persisted in SQLite and records execution-specific information for LIVE/PAPER events. Broker/order/AI records can include:

- environment,
- selected account id,
- security firm,
- source (`MANUAL` or `AI`),
- symbol,
- order id,
- broker status,
- deterministic risk result,
- final LIVE safety checks and blocked reasons.

Additional security/broker events include LIVE account selection, successful unlock, failed unlock, explicit lock and locked trade attempts. LIVE AI safety failures are also logged as risk events.

The UI's Activity / Logs page continues to expose event search, category/level filtering and detailed payload expansion.

## API additions

LIVE development adds:

```text
GET  /api/trading/status
GET  /api/trading/accounts
POST /api/trading/account
POST /api/trading/unlock
POST /api/trading/lock
```

Existing APIs such as `/api/portfolio/`, `/api/orders/`, `/api/orders/preview` and `/api/orders/execute` are environment-aware.

A locked broker action returns an unlock-required response. CerebroUI recognizes it, opens the unlock control, and can retry the original action after unlock.

## Safety boundaries intentionally retained

The LIVE implementation is deliberately conservative:

- whole shares only,
- long-only order validation,
- no automatic short creation,
- no options execution,
- no independent margin-sizing logic,
- regular US session only for LIVE execution,
- `trading.enabled` remains a master kill switch,
- deterministic risk remains mandatory,
- selected account must be REAL, ACTIVE and US-authorized,
- live unlock is explicit and can be re-locked from the UI,
- LIVE BUY cooldown is enforced,
- AI price drift is bounded by the configured slippage limit.

Broker/account permissions still have final authority. A request passing Cerebro risk can still be refused by Moomoo/OpenD.

## First LIVE test checklist

Before testing a real order:

1. Deploy `feature/live-trading`, not `main`.
2. Confirm OpenD is logged in.
3. Configure `MOOMOO_TRADING_PASSWORD_MD5` in Portainer; never commit it.
4. Leave `execution.auto_execute` OFF for the first tests.
5. In Settings, switch `trading.mode` to `live` and save.
6. Confirm the red `LIVE TRADING` badge appears.
7. Click **Unlock Trading**.
8. Confirm the expected REAL account/security firm appears; select it.
9. Unlock and verify the header shows `Unlocked`.
10. Open Portfolio and verify the balance/positions match the REAL account rather than the simulated $1M account.
11. Check `risk.max_order_value`, `risk.max_position_pct`, `risk.max_invested_pct`, `risk.min_cash_reserve_pct`, `risk.max_daily_loss`, `execution.cooldown_minutes` and `execution.max_slippage_pct` before the first live test.
12. Test during the regular US session; LIVE order preview should show the regular-session safety check passing.
13. In Orders, preview a deliberately small whole-share order first.
14. Verify effective order limit, available funds, position %, cash reserve, cooldown and all other checks before considering submission.
15. Confirm LIVE order history and Activity show the resulting environment/account/order information.
16. Use the header control to lock trading again after testing.

## Returning to PAPER

Change **Trading Mode** back to `paper`. Cerebro clears the live unlock state and resumes using the SIMULATE account for Portfolio, Orders and AI context. No LIVE account balance is used for PAPER sizing.

## Development note

Do not merge this LIVE implementation to `main` until it has been validated against the intended OpenD/Moomoo account setup. The stable branch remains the known-good PAPER checkpoint by design.
