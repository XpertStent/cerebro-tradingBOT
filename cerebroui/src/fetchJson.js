// Bound the whole request (including its body), even if a fetch wrapper ignores abort.
export async function fetchJson(url, { timeoutMs = 15000, fetcher = (...args) => fetch(...args),
  controller = new AbortController(), setTimer = setTimeout, clearTimer = clearTimeout, ...options } = {}) {
  let timer;
  try {
    return await Promise.race([
      (async () => {
        const response = await fetcher(url, { ...options, signal: controller.signal });
        const contentType = response.headers?.get('content-type');
        if (contentType && !contentType.includes('json')) {
          throw new Error(response.redirected
            ? 'Your access session may have expired. Refresh the page and sign in again.'
            : 'The server returned an unexpected response. Check the Cerebro backend or proxy.');
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail?.message || (typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`));
        return data;
      })(),
      new Promise((_, reject) => {
        timer = setTimer(() => {
          reject(new Error('OpenD request timed out. Please try again; check OpenD if this continues.'));
          controller.abort();
        }, timeoutMs);
      })
    ]);
  } finally {
    clearTimer(timer);
  }
}
