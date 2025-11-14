"""Core extraction logic for Substack notes."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

__all__ = ["NoteExtractor", "NoteData", "ExtractionError"]


@dataclass
class NoteData:
    """Structured information pulled from a single Substack note."""

    url: str
    account_name: Optional[str]
    date_posted: Optional[str]
    text: str
    likes: Optional[int]
    comments: Optional[int]
    restacks: Optional[int]
    has_image: bool
    has_video: bool

    def to_dict(self) -> Dict[str, object]:
        """Return a dictionary representation suitable for serialisation."""

        return asdict(self)


class ExtractionError(RuntimeError):
    """Raised when a Substack note could not be extracted."""


class _BodyTextExtractor(HTMLParser):
    """HTML parser that captures the text content for a note body."""

    _BODY_HINTS = (
        "data-note-body",
        "data-note-content",
        "data-testid=\"post-body\"",
        "data-testid=\"note-body\"",
        "notes-note-body",
        "post-body",
        "body__content",
        "body-post",
        "entry-content",
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_level = 0
        self._text_parts: List[str] = []
        self._stack: List[str] = []
        self._pending_space = False
        self._in_li = False
        self.has_image = False
        self.has_video = False

    def _match_body(self, attrs: Sequence[Tuple[str, Optional[str]]]) -> bool:
        if not attrs:
            return False
        for name, value in attrs:
            if value is None:
                if name in {"data-note-body", "data-note-content"}:
                    return True
            else:
                combined = f"{name}={value}".lower()
                for hint in self._BODY_HINTS:
                    if hint in combined:
                        return True
        return False

    # HTMLParser overrides -------------------------------------------------

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self._stack.append(tag)
        if self._capture_level:
            self._capture_level += 1
        elif self._match_body(attrs):
            self._capture_level = 1

        if not self._capture_level:
            return

        if tag in {"p", "div", "section", "article"}:
            self._ensure_newline()
        elif tag == "br":
            self._text_parts.append("\n")
        elif tag == "li":
            self._ensure_newline()
            self._text_parts.append("- ")
            self._in_li = True
        elif tag in {"img", "picture"}:
            self.has_image = True
        elif tag in {"video", "iframe", "embed"}:
            self.has_video = True

    def handle_endtag(self, tag: str) -> None:
        if self._capture_level:
            if tag == "li":
                self._text_parts.append("\n")
                self._in_li = False
            elif tag in {"p", "div", "section", "article"}:
                self._ensure_newline()

            self._capture_level -= 1

        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._capture_level:
            return
        if self._in_li and not self._text_parts:
            self._text_parts.append("- ")
        self._text_parts.append(data)

    # Helpers ---------------------------------------------------------------

    def _ensure_newline(self) -> None:
        if not self._text_parts:
            return
        if not self._text_parts[-1].endswith("\n"):
            self._text_parts.append("\n")

    def get_text(self) -> str:
        text = "".join(self._text_parts)
        lines = [line.rstrip() for line in text.splitlines()]
        # Remove duplicate empty lines while preserving intentional spacing.
        cleaned: List[str] = []
        previous_blank = False
        for line in lines:
            blank = line == ""
            if blank and previous_blank:
                continue
            cleaned.append(line)
            previous_blank = blank
        return "\n".join(cleaned).strip()


class NoteExtractor:
    """Fetch and normalise content from Substack notes."""

    _JSON_LD_RE = re.compile(
        r"<script[^>]+type=\"application/ld\+json\"[^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, *, timeout: int = 30, user_agent: Optional[str] = None) -> None:
        self.timeout = timeout
        self.user_agent = (
            user_agent
            or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )

    # Public API -----------------------------------------------------------

    def extract(self, url: str, *, cookie: Optional[str] = None) -> NoteData:
        """Fetch *url* and return :class:`NoteData`."""

        html, final_url = self._download(url, cookie=cookie)
        data = self._find_jsonld(html)
        body_text, media_flags = self._extract_body(html, data)
        counts = self._extract_counts(html, data)

        return NoteData(
            url=final_url,
            account_name=self._extract_account(data),
            date_posted=self._extract_date(data),
            text=body_text,
            likes=counts.get("likes"),
            comments=counts.get("comments"),
            restacks=counts.get("restacks"),
            has_image=media_flags[0],
            has_video=media_flags[1],
        )

    # Download -------------------------------------------------------------

    def _download(self, url: str, *, cookie: Optional[str] = None) -> Tuple[str, str]:
        headers = {"User-Agent": self.user_agent}
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset, errors="replace")
                final_url = response.geturl()
        except HTTPError as exc:  # pragma: no cover - network dependant
            raise ExtractionError(f"HTTP error {exc.code} while fetching {url}") from exc
        except URLError as exc:  # pragma: no cover - network dependant
            raise ExtractionError(f"Failed to fetch {url}: {exc.reason}") from exc
        return html, final_url

    # JSON-LD parsing ------------------------------------------------------

    def _find_jsonld(self, html: str) -> Optional[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        for match in self._JSON_LD_RE.finditer(html):
            fragment = match.group(1).strip()
            if not fragment:
                continue
            try:
                data = json.loads(fragment)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                candidates.append(data)
            elif isinstance(data, list):
                candidates.extend(item for item in data if isinstance(item, dict))

        preferred_types = {"SocialMediaPosting", "Article", "BlogPosting"}
        for candidate in candidates:
            type_hint = candidate.get("@type")
            if isinstance(type_hint, str) and type_hint in preferred_types:
                return candidate
            if isinstance(type_hint, list) and any(t in preferred_types for t in type_hint if isinstance(t, str)):
                return candidate
        return candidates[0] if candidates else None

    # Body extraction ------------------------------------------------------

    def _extract_body(self, html: str, jsonld: Optional[Dict[str, object]]) -> Tuple[str, Tuple[bool, bool]]:
        text: Optional[str] = None
        has_image = False
        has_video = False

        if jsonld:
            text = self._coerce_text(jsonld)
            has_image = self._jsonld_has_media(jsonld, "image")
            has_video = self._jsonld_has_media(jsonld, "video")

        if text:
            text = text.strip()

        if not text or not text.strip():
            parser = _BodyTextExtractor()
            parser.feed(html)
            text = parser.get_text()
            has_image = has_image or parser.has_image
            has_video = has_video or parser.has_video

        if text:
            text = self._normalise_whitespace(text)
        else:
            text = ""

        return text, (has_image, has_video)

    def _coerce_text(self, jsonld: Dict[str, object]) -> Optional[str]:
        body_fields = ("articleBody", "text", "description")
        for field in body_fields:
            value = jsonld.get(field)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _jsonld_has_media(self, jsonld: Dict[str, object], key: str) -> bool:
        value = jsonld.get(key)
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, dict):
            return True
        if isinstance(value, list):
            return any(bool(item) for item in value)
        return False

    def _normalise_whitespace(self, text: str) -> str:
        return "\n".join(line.rstrip() for line in text.splitlines()).strip()

    # Metadata -------------------------------------------------------------

    def _extract_account(self, jsonld: Optional[Dict[str, object]]) -> Optional[str]:
        if not jsonld:
            return None
        author = jsonld.get("author")
        if isinstance(author, dict):
            name = author.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        elif isinstance(author, list):
            for item in author:
                if isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
        publisher = jsonld.get("publisher")
        if isinstance(publisher, dict):
            name = publisher.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return None

    def _extract_date(self, jsonld: Optional[Dict[str, object]]) -> Optional[str]:
        if not jsonld:
            return None
        for key in ("datePublished", "dateCreated", "uploadDate"):
            value = jsonld.get(key)
            if isinstance(value, str) and value.strip():
                return self._normalise_date(value)
        return None

    def _normalise_date(self, value: str) -> str:
        value = value.strip()
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            return value

    # Metrics --------------------------------------------------------------

    def _extract_counts(
        self, html: str, jsonld: Optional[Dict[str, object]]
    ) -> Dict[str, Optional[int]]:
        counts = {"likes": None, "comments": None, "restacks": None}

        if jsonld:
            stats = jsonld.get("interactionStatistic")
            for name, value in self._counts_from_interactions(stats).items():
                counts[name] = value

        if counts["likes"] is None:
            counts["likes"] = self._search_count(html, self._like_patterns())
        if counts["comments"] is None:
            counts["comments"] = self._search_count(html, self._comment_patterns())
        if counts["restacks"] is None:
            counts["restacks"] = self._search_count(html, self._restack_patterns())

        return counts

    def _counts_from_interactions(self, stats: object) -> Dict[str, Optional[int]]:
        counts: Dict[str, Optional[int]] = {}
        if isinstance(stats, dict):
            iterable = [stats]
        elif isinstance(stats, list):
            iterable = [item for item in stats if isinstance(item, dict)]
        else:
            iterable = []

        for entry in iterable:
            type_hint = entry.get("interactionType") or entry.get("@type")
            type_id = self._interaction_type_to_string(type_hint)
            count = self._coerce_int(entry.get("userInteractionCount"))
            if count is None:
                continue
            if "like" in type_id:
                counts.setdefault("likes", count)
            elif "comment" in type_id or "reply" in type_id:
                counts.setdefault("comments", count)
            elif any(key in type_id for key in ("share", "reshare", "repost", "retweet", "restack")):
                counts.setdefault("restacks", count)
        return counts

    def _interaction_type_to_string(self, type_hint: object) -> str:
        if isinstance(type_hint, dict):
            type_value = type_hint.get("@type") or type_hint.get("@id")
            return str(type_value or "").lower()
        if isinstance(type_hint, list):
            return " ".join(str(item).lower() for item in type_hint)
        if isinstance(type_hint, str):
            return type_hint.lower()
        return ""

    def _coerce_int(self, value: object) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            digits = re.sub(r"[^0-9]", "", value)
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    return None
        return None

    def _search_count(self, html: str, patterns: Sequence[re.Pattern[str]]) -> Optional[int]:
        for pattern in patterns:
            match = pattern.search(html)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, TypeError):
                    continue
        return None

    def _like_patterns(self) -> Sequence[re.Pattern[str]]:
        return (
            re.compile(r'"likes"\s*:\s*(\d+)', re.IGNORECASE),
            re.compile(r'data-testid="likes?-count"[^>]*>(\d+)', re.IGNORECASE),
            re.compile(r'aria-label="(\d+)\s+likes?"', re.IGNORECASE),
        )

    def _comment_patterns(self) -> Sequence[re.Pattern[str]]:
        return (
            re.compile(r'"comments"\s*:\s*(\d+)', re.IGNORECASE),
            re.compile(r'data-testid="comments?-count"[^>]*>(\d+)', re.IGNORECASE),
            re.compile(r'aria-label="(\d+)\s+comments?"', re.IGNORECASE),
        )

    def _restack_patterns(self) -> Sequence[re.Pattern[str]]:
        return (
            re.compile(r'"restacks"\s*:\s*(\d+)', re.IGNORECASE),
            re.compile(r'"reposts"\s*:\s*(\d+)', re.IGNORECASE),
            re.compile(r'data-testid="restacks?-count"[^>]*>(\d+)', re.IGNORECASE),
            re.compile(r'aria-label="(\d+)\s+restacks?"', re.IGNORECASE),
        )


# Utility helpers ----------------------------------------------------------

def notes_to_csv(path: str, notes: Sequence[NoteData]) -> None:
    """Persist *notes* to *path* as a CSV file."""

    fieldnames = [
        "url",
        "account_name",
        "date_posted",
        "text",
        "likes",
        "comments",
        "restacks",
        "has_image",
        "has_video",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for note in notes:
            writer.writerow(note.to_dict())


def notes_to_tsv(path: str, notes: Sequence[NoteData]) -> None:
    """Persist *notes* to *path* as a TSV file."""

    fieldnames = [
        "url",
        "account_name",
        "date_posted",
        "text",
        "likes",
        "comments",
        "restacks",
        "has_image",
        "has_video",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for note in notes:
            writer.writerow(note.to_dict())
