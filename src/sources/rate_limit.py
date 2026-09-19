"""Small per-source request pacer shared by network adapters."""

from __future__ import annotations

import threading
import time


class RequestPacer:
    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if self.delay_seconds <= 0:
            return
        with self._lock:
            remaining = self.delay_seconds - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request = time.monotonic()
