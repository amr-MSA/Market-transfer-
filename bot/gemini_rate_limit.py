"""Shared pacing and retry policy for every direct Gemini request.

The bot deliberately performs classification and editorial writing as separate
requests. Without one shared limiter those calls can arrive back-to-back and a
temporary 429/5xx response is easily mistaken for a rejected article.
"""

from __future__ import annotations

import time

import requests


class GeminiTransientError(RuntimeError):
    """A request can safely be retried in this or a future polling cycle."""


class GeminiRateLimiter:
    def __init__(
        self,
        min_interval_seconds=4.0,
        max_retries=2,
        retry_backoff_seconds=4.0,
        sleep_fn=time.sleep,
        clock=time.monotonic,
    ):
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.sleep_fn = sleep_fn
        self.clock = clock
        self._last_request_at = None

    def _wait_for_slot(self):
        if self._last_request_at is None or not self.min_interval_seconds:
            return
        remaining = self.min_interval_seconds - (self.clock() - self._last_request_at)
        if remaining > 0:
            self.sleep_fn(remaining)

    def _retry_delay(self, response, attempt):
        retry_after = None
        try:
            retry_after = float(response.headers.get("Retry-After"))
        except (AttributeError, TypeError, ValueError):
            pass
        exponential = self.retry_backoff_seconds * (2 ** attempt)
        return max(exponential, retry_after or 0.0)

    def post(self, request_fn, *args, **kwargs):
        """Call a supplied requests.post function under shared pacing.

        ``request_fn`` is injected by the caller so tests can continue to
        replace each module's local ``requests.post`` without real HTTP.
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            self._wait_for_slot()
            try:
                response = request_fn(*args, **kwargs)
                self._last_request_at = self.clock()
                status_code = getattr(response, "status_code", None)
                if status_code in {429, 500, 502, 503, 504}:
                    raise GeminiTransientError(f"Gemini temporary HTTP {status_code}")
                response.raise_for_status()
                return response
            except GeminiTransientError as exc:
                last_error = exc
                response = locals().get("response")
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                response = None
            except requests.RequestException:
                raise

            if attempt < self.max_retries:
                self.sleep_fn(self._retry_delay(response, attempt))

        raise GeminiTransientError(str(last_error or "Gemini request temporarily unavailable"))
