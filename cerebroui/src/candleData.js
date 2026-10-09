export function mergeCandles(previous, incoming) {
  const rows = new Map(previous.map(candle => [candle.time, candle]));
  for (const candle of incoming) rows.set(candle.time, candle);
  return [...rows.values()].sort((a, b) => a.time.localeCompare(b.time));
}

export function sameCandleSeries(candle, metadata) {
  return ["provider", "feed", "adjustment", "session", "timeframe", "adjustment_basis"]
    .every(key => candle?.[key] === metadata?.[key]);
}

export function mergeCandleResponse(previous, response, quiet) {
  const incoming = response.candles || [];
  return quiet && previous.length && sameCandleSeries(previous[0], response)
    ? mergeCandles(previous, incoming) : incoming;
}

export function prependedCount(previous, incoming) {
  if (!previous.length) return 0;
  return incoming.filter(candle => candle.time < previous[0].time).length;
}
