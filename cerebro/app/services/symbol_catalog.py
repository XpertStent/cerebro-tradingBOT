"""Share catalog loads without leaving API requests waiting indefinitely."""
import threading
import time


class SymbolCatalogTimeout(RuntimeError):
    pass


class SymbolCatalogCache:
    def __init__(self, ttl=21600, retry_after=30, wait_timeout=4):
        self.ttl = ttl
        self.retry_after = retry_after
        self.wait_timeout = wait_timeout
        self._entries = {}
        self._loading = {}
        self._lock = threading.Lock()

    def _load(self, key, loader, previous, pending):
        try:
            updated = dict(items=tuple(loader()), error=None,
                           expires=time.monotonic() + self.ttl)
        except Exception as exc:
            updated = dict(items=previous['items'] if previous else (),
                           error=None if previous and not previous['error'] else str(exc),
                           expires=time.monotonic() + self.retry_after)
        with self._lock:
            self._entries[key] = updated
            self._loading.pop(key, None)
            pending.set()

    def get(self, key, loader, wait_timeout=None):
        budget = self.wait_timeout if wait_timeout is None else max(0, wait_timeout)
        deadline = time.monotonic() + budget
        while True:
            with self._lock:
                entry = self._entries.get(key)
                if entry and time.monotonic() < entry['expires']:
                    if entry['error']:
                        raise RuntimeError(entry['error'])
                    return entry['items']
                pending = self._loading.get(key)
                if pending is None:
                    pending = self._loading[key] = threading.Event()
                    # One daemon per reference-data key. A stuck SDK call cannot
                    # occupy an API worker or trigger duplicate catalog downloads.
                    threading.Thread(target=self._load, args=(key, loader, entry, pending),
                                     name='opend-symbol-catalog', daemon=True).start()
            if not pending.wait(max(0, deadline - time.monotonic())):
                if entry and not entry['error']:
                    return entry['items']
                raise SymbolCatalogTimeout("OpenD securities list is still loading. Try searching again shortly.")
