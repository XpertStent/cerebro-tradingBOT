export function historyDate(value) {
  if (value == null || value === "") return "—";
  const text = String(value);
  const match = /^(\d{4})-?(\d{2})-?(\d{2})(?:$|[ T])/.exec(text);
  if (!match) return "—";
  const [, year, month, day] = match;
  const date = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== `${year}-${month}-${day}`) return "—";
  return date.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function historyNumber(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-AU", { maximumFractionDigits: 3 }) : "—";
}

export function historyStatus(status) {
  return { RUNNING: "Analysing", ANALYSED: "Ready for ranking", SKIPPED: "Skipped", ERROR: "Analysis failed" }[status] || status || "Pending";
}

export function historySource(detail) {
  if (detail.refresh_error) return "Cached fallback (refresh failed)";
  if ((detail.fetched_count || 0) > 0) return "Provider download + cache";
  if (detail.source === "CACHE") return "Cache hit";
  return detail.source || (detail.status === "RUNNING" ? "Pending" : "No history received");
}
