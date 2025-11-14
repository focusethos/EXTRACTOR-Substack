"""Batch helpers for orchestrating multiple Substack extractions."""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Sequence, Tuple

from .extractor import ExtractionError, NoteData, NoteExtractor

SleepFunc = Callable[[float], None]


class BatchExtractor:
    """Coordinate multiple :class:`NoteExtractor` calls with throttling."""

    def __init__(
        self,
        extractor: NoteExtractor,
        *,
        delay: float = 0.0,
        max_retries: int = 1,
        retry_backoff: float = 2.0,
        cookies: Optional[Sequence[str]] = None,
        sleep: Optional[SleepFunc] = None,
    ) -> None:
        if delay < 0:
            raise ValueError("delay must be >= 0")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if retry_backoff < 1:
            raise ValueError("retry_backoff must be >= 1")

        self.extractor = extractor
        self.delay = float(delay)
        self.max_retries = int(max_retries)
        self.retry_backoff = float(retry_backoff)
        self._cookies: List[str] = []
        if cookies:
            self._cookies = [c.strip() for c in cookies if c and c.strip()]
        self._cookie_index = 0
        self._sleep: SleepFunc = sleep or time.sleep

    # Public API -----------------------------------------------------------

    def extract_all(self, urls: Sequence[str]) -> Tuple[List[NoteData], List[str]]:
        """Return successful notes and failure messages for *urls*."""

        successes: List[NoteData] = []
        failures: List[str] = []

        for index, url in enumerate(urls):
            note, error = self._extract_with_retries(url, index)
            if note:
                successes.append(note)
            elif error:
                failures.append(error)

        return successes, failures

    # Internal helpers ----------------------------------------------------

    def _next_cookie(self) -> Optional[str]:
        if not self._cookies:
            return None
        cookie = self._cookies[self._cookie_index]
        self._cookie_index = (self._cookie_index + 1) % len(self._cookies)
        return cookie

    def _sleep_for(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._sleep(seconds)

    def _extract_with_retries(self, url: str, index: int) -> Tuple[Optional[NoteData], Optional[str]]:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            wait_seconds = 0.0
            if index > 0 or attempt > 0:
                wait_seconds = self.delay * (self.retry_backoff ** attempt)
            self._sleep_for(wait_seconds)

            cookie = self._next_cookie()
            try:
                note = self.extractor.extract(url, cookie=cookie)
                return note, None
            except ExtractionError as exc:
                last_error = exc
            except Exception as exc:  # pragma: no cover - defensive guard
                last_error = exc
                break

        error_message = f"{url}: {last_error}" if last_error else f"{url}: unknown error"
        return None, error_message


__all__ = ["BatchExtractor"]

