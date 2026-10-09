import { fetchJson } from './fetchJson.js';
const cache = new Map();
const TTL = 60000;

// Each field owns cancellation and generation state; cached results are shared.
export function createSymbolSearch({ publish, fetcher = (...args) => fetch(...args), delay = 250,
  setTimer = setTimeout, clearTimer = clearTimeout, now = Date.now, timeoutMs = 15000 } = {}) {
  let generation = 0;
  let timer;
  let controller;

  function cancel(notify = true) {
    generation += 1;
    clearTimer(timer);
    controller?.abort();
    if (notify) publish({ results: [], searching: false, error: null });
  }

  async function run(value, { markets, limit = 12 } = {}) {
    cancel(false);
    const id = generation;
    const query = value.trim();
    if (!query || !markets?.length) {
      publish({ results: [], searching: false, error: null });
      return;
    }
    const key = JSON.stringify([query.toLowerCase(), [...markets].sort(), limit]);
    const cached = cache.get(key);
    if (cached && now() - cached.at < TTL) {
      publish({ results: cached.results, searching: false, error: null });
      return cached.results;
    }
    controller = new AbortController();
    publish({ results: [], searching: true, error: null });
    try {
      const params = new URLSearchParams({ q: query, markets: markets.join(','), limit: String(limit) });
      const data = await fetchJson(`/api/market/search?${params}`, { cache: 'no-store', controller,
        fetcher, timeoutMs, setTimer, clearTimer });
      if (id !== generation) return;
      const results = data.results || [];
      if (results.length) {
        cache.delete(key);
        cache.set(key, { results, at: now() });
        if (cache.size > 100) cache.delete(cache.keys().next().value);
      }
      publish({ results, searching: false, error: null });
      return results;
    } catch (error) {
      if (id === generation) publish({ results: [], searching: false, error: error.name === 'AbortError' ? 'Search interrupted. Please try again.' : error.message });
    }
  }

  function schedule(value, options) {
    cancel();
    if (value.trim().length < (options?.minLength ?? 2)) return;
    publish({ results: [], searching: true, error: null });
    timer = setTimer(() => run(value, options), delay);
  }

  return { run, schedule, cancel };
}
