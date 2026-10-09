export function historyQuotaFailure(failure) {
  return failure.code === 'HISTORICAL_CANDLE_QUOTA_EXHAUSTED' ||
    /quota/i.test(failure.message || '') && /historical|k-line|kline/i.test(failure.message || '');
}

export function candleFailureMessage(failure) {
  if (!historyQuotaFailure(failure)) return failure.message;
  return 'OpenD historical candle quota is full. Slots are released seven days after use. ' +
    'Quotes can still load. Automatic candle retries are paused; retry Search after quota becomes available. ' +
    'This is a market-data limit, unrelated to trading unlock.';
}
