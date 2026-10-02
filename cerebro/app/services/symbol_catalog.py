"""Cache OpenD reference data, sharing one load across concurrent searches."""
import threading
import time


class SymbolCatalogCache:
    def __init__(self, ttl=21600, retry_after=30):
        self.ttl = ttl
        self.retry_after = retry_after
        self._entries = {}
        self._loading = {}
        self._lock = threading.Lock()

    def get(self, key, loader):
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
                    break
            pending.wait()

        updated = None
        try:
            items = tuple(loader())
            updated = dict(items=items, error=None, expires=time.monotonic() + self.ttl)
        except Exception as exc:
            # A refresh failure must not discard the last successful catalog.
            updated = dict(items=entry['items'] if entry else (),
                           error=None if entry and not entry['error'] else str(exc),
                           expires=time.monotonic() + self.retry_after)
        finally:
            with self._lock:
                if updated is not None:
                    self._entries[key] = updated
                self._loading.pop(key).set()
        if updated['error']:
            raise RuntimeError(updated['error'])
        return updated['items']
