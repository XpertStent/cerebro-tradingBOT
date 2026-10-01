import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeCandles, prependedCount } from '../src/candleData.js';

test('backfill and live refresh retain earlier candles without duplicate bars', () => {
  const previous = [{time:'2026-09-30 10:00:00',close:10}, {time:'2026-09-30 11:00:00',close:11}];
  const older = [{time:'2026-09-30 09:00:00',close:9},previous[0]];
  const combined = mergeCandles(previous, older);
  assert.equal(prependedCount(previous, combined), 1);
  const refreshed = mergeCandles(combined, [{time:'2026-09-30 11:00:00',close:12}]);
  assert.equal(refreshed.length, 3);
  assert.equal(refreshed[0].close, 9);
  assert.equal(refreshed.at(-1).close, 12);
  const viewport = {from:1,to:2};
  const shift = prependedCount(previous, combined);
  assert.equal(combined[viewport.from + shift].time, previous[viewport.from].time);
});
