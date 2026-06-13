"""Polite HTTP client: fixed inter-request delay, timeouts, retries with backoff.

Used for every live fetch. Conservative by default; rates come from settings/config.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx

from vehicle_finder.config import Settings, get_settings
from vehicle_finder.logging import get_logger

log = get_logger("http")

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PoliteClient:
    """Wraps httpx.Client with a minimum delay between requests and bounded retries."""

    def __init__(
        self,
        settings: Settings | None = None,
        min_delay: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.min_delay = self.settings.request_delay_seconds if min_delay is None else min_delay
        self.max_retries = self.settings.http_max_retries
        self._client = client or httpx.Client(
            headers={"User-Agent": self.settings.user_agent},
            timeout=self.settings.http_timeout,
            follow_redirects=True,
        )
        self._last_request_at: float = 0.0

    def _respect_delay(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Issue a request, retrying transient failures with exponential backoff."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._respect_delay()
            try:
                resp = self._client.request(
                    method, url, headers=headers, json=json_body, params=params
                )
                self._last_request_at = time.monotonic()
                if resp.status_code in _RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                self._last_request_at = time.monotonic()
                backoff = min(2.0 ** (attempt - 1), 30.0)
                log.warning(
                    "http_retry", url=url, attempt=attempt, max=self.max_retries, error=str(exc)
                )
                if attempt < self.max_retries:
                    time.sleep(backoff)
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
