export function mergeCandles(previous, incoming) {
  const rows = new Map(previous.map(candle => [candle.time, candle]));
  for (const candle of incoming) rows.set(candle.time, candle);
  return [...rows.values()].sort((a, b) => a.time.localeCompare(b.time));
}

export function prependedCount(previous, incoming) {
  if (!previous.length) return 0;
  return incoming.filter(candle => candle.time < previous[0].time).length;
}
