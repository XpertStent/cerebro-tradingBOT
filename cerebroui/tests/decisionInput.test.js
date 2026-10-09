import test from "node:test";
import assert from "node:assert/strict";
import { inputGroups, requestText } from "../src/decisionInput.js";

test("input breakdown preserves complete symbol entries and all shared context fields", () => {
  const candidate = { symbol: "US.TEST", research_context: null, unknown_future_field: { values: [1, 2] } };
  const snapshot = { context: { candidates: [candidate], portfolio: { cash: 100 }, new_shared_field: "retain me" } };
  const groups = inputGroups(snapshot);
  assert.deepEqual(groups.candidates, [candidate]);
  assert.deepEqual(groups.shared, { portfolio: { cash: 100 }, new_shared_field: "retain me" });
  assert.deepEqual(snapshot.context.candidates, [candidate]);
});

test("copied request preserves the exact prompt, schema and tool configuration", () => {
  const snapshot = { request: { model: "fake", input: 'Instructions\n{"news":"café and \\\"quotes\\\""}', text: { format: { type: "json_schema" } }, tools: [{ type: "web_search" }] } };
  assert.deepEqual(JSON.parse(requestText(snapshot)), snapshot.request);
  assert.deepEqual(inputGroups(null), { candidates: [], shared: {} });
});
