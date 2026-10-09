# Technical pattern analysis

Daily analysis supplements the existing quant engine. It uses TA-Lib 0.8.1
(all 61 candlestick detectors) and ta-patterns 1.2.1 (15 selected formations:
doubles, head and shoulders, triangles, wedges, flags, pennants, rectangles).
TradingPatternScanner and the separate chart_patterns package are not dependencies.

## Operator controls

Settings → Technical Patterns selects **Off**, **Observation only** (default), or
**AI advisory**. Observation stores/displays results but excludes them from AI
prompts and quant scores. Advisory supplies compact per-symbol evidence alongside
the existing portfolio, research and risk context. Neither mode arms orders.
Pattern evidence has no quant ranking weight; equal existing factor values now
receive equal percentile ranks.

Family toggles, swing confirmation delay, geometry tolerances, breakout buffer,
volume requirement and expiry are configurable. History Fetch Count still
controls the shared historical fetch, with enough completed candles requested
for the configured pattern window. Intraday pattern analysis is not enabled.

## Data and timing

The selected Alpaca/OpenD provider supplies the existing completed-history path.
Quant passes those same candles directly to analysis. Holdings, pending orders
and monitored securities outside quant use that same cache-backed path.
TA-Lib and chart formation analysis run independently on the same arrays; they
do not issue provider requests. Stale, incomplete, invalid or mixed-provenance
history produces an explicit unavailable result, never an old cached signal.

Actual swings define geometry. Recognition is dated only after pivot confirmation;
breakout confirmation requires a subsequent completed close beyond a boundary
and the configured ATR buffer/optional volume ratio. Unconfirmed formations can
expire or invalidate; confirmed formations can fail. Historical recognition dates
are reconstructed evidence, not proof that Cerebro observed them then:
`first_observed_at` records the actual observation time separately.

## Isolation and explanation

`/data/technical_patterns.db` stores results and event observations beside the
existing persistent databases. Result keys include symbol, timeframe, provider,
feed, adjustment/revision, session, settings, integration version and candle
fingerprint. Revisions force recalculation; first observation survives revisions
within the same provider/settings namespace. Saved evidence is revalidated
against the current completed session before entering AI input.

The versioned private adapter corrects future indexing in flagpoles, pivot warmup,
actual-price swing filtering, confirmation-index geometry and price-scale slope
thresholds. Geometry checks reject weak or incompatible shapes. Overlapping
family/direction results are grouped in AI context rather than counted as votes.
Signed TA-Lib outputs and geometric fit values are not success probabilities.
Adjusted historical levels are not executable raw order prices.

Markets shows expandable records and optional daily overlays only when chart
provenance, adjustment revision and latest completed close agree. Markers distinguish
swings, recognition and confirmation; lines end at available evaluated candles.
Workflow activity expands pattern details in place. The decision-input inspector
shows the compact evidence actually supplied when advisory mode is enabled.

## Validation and maintenance

Keep the regression suite: it checks prefix replay (no backdated signals), price
scaling, geometry dates, lifecycle transitions, stale/cache/provider separation,
observation exclusion, AI context and chart alignment. Tests run during development
and CI, never as part of trading or paid model requests. CI uses Python 3.14 to
match the Docker base. Library upgrades require a new adapter version and replay
checks. Passing these tests establishes integration behavior, not profitability.

NumPy is explicit in requirements. Pandas is optional for pattern DataFrame
helpers, but the existing broker SDK still depends on it. TA-Lib distributes its
license in wheel metadata; ta-patterns declares MIT in package metadata/upstream
documentation but its audited source did not contain a standalone LICENSE file.
No full third-party implementation is vendored here.
