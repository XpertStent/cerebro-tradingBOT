import test from "node:test";
import assert from "node:assert/strict";
import { historyDate, historyNumber, historyStatus, historySource } from "../src/workflowHistory.js";

test("daily history dates preserve the trading date rather than converting midnight", () => {
  assert.equal(historyDate("2026-10-08 00:00:00"), "8 Oct 2026");
  assert.equal(historyDate(20261008), "8 Oct 2026");
  for (const value of [null, undefined, "undefined", "2026-02-30", ""]) assert.equal(historyDate(value), "—");
});

test("history distinguishes zero downloads, missing counts, mixed downloads and failed cache refresh", () => {
  assert.equal(historyNumber(0), "0");
  assert.equal(historyNumber(null), "—");
  assert.equal(historyNumber(1000), "1,000");
  assert.equal(historySource({ source: "CACHE", fetched_count: 0 }), "Cache hit");
  assert.equal(historySource({ source: "CACHE", fetched_count: 500 }), "Provider download + cache");
  assert.equal(historySource({ source: "CACHE", refresh_error: { code: "FAILED" } }), "Cached fallback (refresh failed)");
  assert.equal(historyStatus("SKIPPED"), "Skipped");
});
