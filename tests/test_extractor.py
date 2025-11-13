from __future__ import annotations

import unittest

from substack_extractor.extractor import NoteExtractor, NoteData


class _FakeExtractor(NoteExtractor):
    def __init__(self, html: str):
        super().__init__(timeout=1)
        self._html = html

    def _download(self, url: str):  # type: ignore[override]
        return self._html, url


class NoteExtractorTests(unittest.TestCase):
    def test_extract_uses_jsonld(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@type": "SocialMediaPosting",
                "author": {"name": "Example Author"},
                "datePublished": "2024-01-02T15:04:05Z",
                "articleBody": "First paragraph.\\n\\n• Bullet one\\n• Bullet two",
                "interactionStatistic": [
                  {
                    "@type": "InteractionCounter",
                    "interactionType": "https://schema.org/LikeAction",
                    "userInteractionCount": 42
                  },
                  {
                    "@type": "InteractionCounter",
                    "interactionType": {"@type": "CommentAction"},
                    "userInteractionCount": "7"
                  },
                  {
                    "@type": "InteractionCounter",
                    "interactionType": "ShareAction",
                    "userInteractionCount": 3
                  }
                ],
                "image": "https://example.com/image.jpg"
              }
            </script>
          </head>
          <body>
            <div data-testid="post-body">
              <p>Ignored body copy.</p>
            </div>
          </body>
        </html>
        """
        extractor = _FakeExtractor(html)
        note = extractor.extract("https://example.com/note")

        self.assertIsInstance(note, NoteData)
        self.assertEqual(note.account_name, "Example Author")
        self.assertEqual(note.date_posted, "2024-01-02T15:04:05+00:00")
        self.assertIn("• Bullet one", note.text)
        self.assertEqual(note.likes, 42)
        self.assertEqual(note.comments, 7)
        self.assertEqual(note.restacks, 3)
        self.assertTrue(note.has_image)
        self.assertFalse(note.has_video)

    def test_extract_falls_back_to_html_body(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@type": "Article",
                "author": {"name": "Fallback Author"},
                "dateCreated": "2023-12-24T09:30:00-05:00",
                "articleBody": ""
              }
            </script>
          </head>
          <body>
            <div data-testid="post-body">
              <p>First paragraph.</p>
              <ul>
                <li>Item one</li>
                <li>Item two</li>
              </ul>
              <img src="image.png" alt="" />
            </div>
          </body>
        </html>
        """
        extractor = _FakeExtractor(html)
        note = extractor.extract("https://example.com/fallback")

        self.assertEqual(note.account_name, "Fallback Author")
        self.assertEqual(note.date_posted, "2023-12-24T09:30:00-05:00")
        self.assertIn("- Item one", note.text)
        self.assertTrue(note.has_image)
        self.assertFalse(note.has_video)


if __name__ == "__main__":
    unittest.main()
