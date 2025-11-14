from __future__ import annotations

import unittest

from substack_extractor.batch import BatchExtractor
from substack_extractor.extractor import ExtractionError, NoteData


class _StubExtractor:
    def __init__(self) -> None:
        self.attempts: dict[str, int] = {}

    def extract(self, url: str, *, cookie: str | None = None) -> NoteData:
        attempt = self.attempts.get(url, 0)
        self.attempts[url] = attempt + 1
        if attempt == 0:
            raise ExtractionError(f"temporary failure for {url}")
        return NoteData(
            url=url,
            account_name="Account",
            date_posted="2024-01-01T00:00:00Z",
            text="Body",
            likes=1,
            comments=2,
            restacks=3,
            has_image=False,
            has_video=False,
        )


class BatchExtractorTests(unittest.TestCase):
    def test_retries_and_cookie_rotation(self) -> None:
        extractor = _StubExtractor()
        sleeps: list[float] = []
        batch = BatchExtractor(
            extractor, delay=1.0, max_retries=2, retry_backoff=3.0, cookies=["cookie=a", "cookie=b"], sleep=sleeps.append
        )

        notes, failures = batch.extract_all(["https://a", "https://b"])

        self.assertEqual(len(notes), 2)
        self.assertFalse(failures)
        # First URL should trigger a retry with exponential backoff (1 * 3^1)
        self.assertIn(3.0, sleeps)
        # Second URL should respect the base delay once the batch has started.
        self.assertIn(1.0, sleeps)

    def test_exhausted_retries_surface_failure(self) -> None:
        class _AlwaysFailingExtractor:
            def extract(self, url: str, *, cookie: str | None = None) -> NoteData:  # pragma: no cover - type contract
                raise ExtractionError("boom")

        batch = BatchExtractor(_AlwaysFailingExtractor(), max_retries=2)
        notes, failures = batch.extract_all(["https://fail"])

        self.assertFalse(notes)
        self.assertEqual(len(failures), 1)
        self.assertIn("https://fail", failures[0])


if __name__ == "__main__":
    unittest.main()

