export const patternName = value => String(value || "Pattern").replaceAll("_", " ").replace(/^hs /, "head and shoulders ");

export function compatiblePatterns(analysis, chart, candles) {
  if (!analysis?.available || !chart || chart.timeframe !== "1d" || analysis.symbol !== chart.symbol) return false;
  if (!["provider", "feed", "adjustment", "session"].every(key => analysis.provenance?.[key] === chart[key])) return false;
  if (analysis.provenance?.adjustment_basis !== chart.adjustment_basis) return false;
  const latest = candles.find(candle => candle.time.slice(0, 10) === analysis.latest_candle_date);
  return !!latest && Math.abs(Number(latest.close) - analysis.latest_close) <= Math.max(1e-6, analysis.latest_close * 1e-7);
}

export function selectedPattern(analysis, id) {
  return analysis?.events?.find(event => event.id === id)
    || analysis?.events?.find(event => ["FORMING", "CONFIRMED"].includes(event.status)) || null;
}

export function patternLines(event, candles) {
  if (!event) return [];
  return (event.lines || []).map(line => {
    const [first, last] = line.points;
    const end = candles.findIndex(candle => candle.time.slice(0, 10) === last.date);
    if (end < 0) return [];
    return candles.flatMap((candle, index) => {
      const time = candle.time.slice(0, 10);
      return time >= first.date && index <= end ? [{ time, value: last.value + line.slope_per_bar * (index - end) }] : [];
    });
  }).filter(line => line.length > 1);
}

export function patternMarkers(event, evidence, candles) {
  const available = new Set(candles.map(candle => candle.time.slice(0, 10)));
  const markers = [];
  if (event) {
    for (const point of event.points || []) markers.push({ time: point.date, position: point.kind === "high" ? "aboveBar" : "belowBar", color: "#64748b", shape: "circle", text: "Swing" });
    markers.push({ time: event.recognition_date, position: "aboveBar", color: "#7c3aed", shape: "circle", text: "Recognized" });
    if (event.confirmation_date) markers.push({ time: event.confirmation_date, position: event.direction === "bearish" ? "aboveBar" : "belowBar", color: event.direction === "bearish" ? "#dc2626" : "#059669", shape: event.direction === "bearish" ? "arrowDown" : "arrowUp", text: "Confirmed" });
  }
  const used = new Set();
  for (const candle of evidence || []) {
    if (used.has(candle.date) || used.size >= 5) continue;
    used.add(candle.date);
    markers.push({ time: candle.date, position: "belowBar", color: "#0891b2", shape: "circle", text: candle.name.replace(/^CDL/, "") });
  }
  return markers.filter(marker => available.has(marker.time)).sort((a, b) => a.time.localeCompare(b.time));
}
