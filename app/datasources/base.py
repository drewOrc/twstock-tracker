import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


class HttpClient:
    """Small wrapper with throttling + retries, shared by the exchange clients."""

    def __init__(self, timeout: float = 20.0, delay: float = 1.5, retries: int = 3, headers: dict | None = None):
        self.timeout = timeout
        self.delay = delay
        self.retries = retries
        self._last_request = 0.0
        self._client = httpx.Client(
            timeout=timeout, headers={**DEFAULT_HEADERS, **(headers or {})}, follow_redirects=True
        )

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            try:
                r = self._client.get(url, params=params, headers=headers)
                r.raise_for_status()
                text = r.text.lstrip()
                if not text.startswith(("{", "[")):
                    raise ValueError(f"non-JSON response from {url}")
                return r.json()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(min(2.0 * attempt, 6.0))
        raise RuntimeError(f"request failed: {url}") from last_exc

    def close(self):
        self._client.close()
