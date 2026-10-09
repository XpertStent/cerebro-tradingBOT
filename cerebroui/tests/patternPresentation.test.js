import test from "node:test";
import assert from "node:assert/strict";
import { compatiblePatterns, patternLines, patternMarkers, selectedPattern } from "../src/patternPresentation.js";

const candles = ["2026-01-02", "2026-01-05", "2026-01-06"].map((date, i) => ({ time: `${date} 00:00:00`, close: 100 + i }));
const basis = { provider: "alpaca", feed: "sip", adjustment: "all", session: "PROVIDER_AGGREGATE", adjustment_basis: "current" };
test("overlays require matching provider, basis, symbol and latest completed price", () => {
  const chart = { ...basis, symbol: "US.TEST", timeframe: "1d" };
  const analysis = { available: true, symbol: "US.TEST", provenance: basis, latest_candle_date: "2026-01-06", latest_close: 102 };
  assert.equal(compatiblePatterns(analysis, chart, candles), true);
  for (const change of [{ provider: "opend" }, { feed: "iex" }, { adjustment: "raw" }, { adjustment_basis: "old" }, { symbol: "US.OTHER" }, { timeframe: "5m" }]) {
    assert.equal(compatiblePatterns(analysis, { ...chart, ...change }, candles), false);
  }
  assert.equal(compatiblePatterns({ ...analysis, latest_close: 110 }, chart, candles), false);
});
test("lines follow candle counts across weekends and never extend the time axis", () => {
  const event = { lines: [{ slope_per_bar: 2, points: [{ date: "2026-01-01", value: 96 }, { date: "2026-01-06", value: 102 }] }] };
  assert.deepEqual(patternLines(event, candles), [[{ time: "2026-01-02", value: 98 }, { time: "2026-01-05", value: 100 }, { time: "2026-01-06", value: 102 }]]);
});
test("recognition markers stay on recognition dates and invisible dates are omitted", () => {
  const event = { points: [{ date: "2026-01-01", kind: "high" }], recognition_date: "2026-01-05", confirmation_date: "2026-01-06", direction: "bullish" };
  const markers = patternMarkers(event, [], candles);
  assert.deepEqual(markers.map(x => x.time), ["2026-01-05", "2026-01-06"]);
  assert.equal(markers[0].text, "Recognized");
  assert.equal(markers[1].text, "Confirmed");
});
test("default selection favors active evidence and explicit historical selection is preserved", () => {
  const analysis = { events: [{ id: "expired", status: "EXPIRED" }, { id: "active", status: "FORMING" }] };
  assert.equal(selectedPattern(analysis)?.id, "active");
  assert.equal(selectedPattern(analysis, "expired")?.id, "expired");
});
