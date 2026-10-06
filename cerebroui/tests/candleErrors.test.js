import assert from 'node:assert/strict';
import test from 'node:test';
import { historyQuotaFailure, candleFailureMessage } from '../src/candleErrors.js';
import { fetchJson } from '../src/fetchJson.js';

test('structured broker quota code reaches the chart and explains the real recovery', async () => {
  let failure;
  try {
    await fetchJson('/candles', { fetcher: async () => ({ok:false,status:503,json:async()=>({detail:{code:'HISTORICAL_CANDLE_QUOTA_EXHAUSTED',message:'Broker unavailable'}})}) });
  } catch (error) { failure = error; }
  assert.equal(historyQuotaFailure(failure), true);
  assert.match(candleFailureMessage(failure), /seven days/);
  assert.match(candleFailureMessage(failure), /Automatic candle retries are paused/);
});

test('old backend quota messages work too; other candle failures remain separate', () => {
  assert.equal(historyQuotaFailure(new Error('Insufficient historical K-line quota.')), true);
  const timeout = new Error('OpenD request timed out');
  assert.equal(historyQuotaFailure(timeout), false);
  assert.equal(candleFailureMessage(timeout), timeout.message);
  assert.equal(historyQuotaFailure(new Error('Subscription quota is full')), false);
});
