"""Command-line interface for the Substack extractor."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from .extractor import (
    ExtractionError,
    NoteData,
    NoteExtractor,
    notes_to_csv,
    notes_to_tsv,
)


def _read_urls_from_file(path: Path) -> List[str]:
    with path.open("r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]


def _read_urls_from_csv(path: Path, column: str | None) -> List[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        field = column or reader.fieldnames[0]
        if field is None:
            raise ValueError("CSV file does not contain any columns")
        urls: List[str] = []
        for row in reader:
            value = row.get(field)
            if value:
                urls.append(value.strip())
        return urls


def _read_urls_from_stdin() -> List[str]:
    return [line.strip() for line in sys.stdin if line.strip()]


def _deduplicate(urls: Iterable[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _render_markdown_table(notes: Sequence[NoteData]) -> str:
    headers = [
        "URL",
        "Account",
        "Date",
        "Text",
        "Likes",
        "Comments",
        "Restacks",
        "Has image",
        "Has video",
    ]
    rows = []
    for note in notes:
        rows.append(
            [
                note.url,
                note.account_name or "",
                note.date_posted or "",
                _format_multiline(note.text),
                _format_optional_int(note.likes),
                _format_optional_int(note.comments),
                _format_optional_int(note.restacks),
                "true" if note.has_image else "false",
                "true" if note.has_video else "false",
            ]
        )

    lines = ["| " + " | ".join(_escape_markdown(cell) for cell in headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(_escape_markdown(cell) for cell in row) + " |")
    return "\n".join(lines)


def _escape_markdown(value: str) -> str:
    escaped = value.replace("|", "\\|")
    return escaped.replace("\n", "<br>")


def _format_optional_int(value: int | None) -> str:
    return "" if value is None else str(value)


def _format_multiline(value: str) -> str:
    return value.strip()


def _write_json(path: Path, notes: Sequence[NoteData]) -> None:
    serialisable = [note.to_dict() for note in notes]
    path.write_text(json.dumps(serialisable, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract structured data from Substack notes")
    source_group = parser.add_argument_group("Input sources")
    source_group.add_argument("--urls", nargs="*", help="One or more Substack note URLs")
    source_group.add_argument("--input", type=Path, help="Path to a text file with one URL per line")
    source_group.add_argument(
        "--csv",
        type=Path,
        help="Path to a CSV file containing URLs",
    )
    source_group.add_argument(
        "--csv-column",
        help="Column name within the CSV file that contains URLs (defaults to the first column)",
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read URLs from standard input",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Network timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--user-agent",
        help="Custom HTTP user agent string",
    )
    parser.add_argument(
        "--export",
        action="append",
        metavar="FORMAT:PATH",
        help="Persist the results (supported formats: csv, tsv, json, md, markdown)",
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="Do not print the Markdown table to stdout",
    )
    return parser.parse_args(argv)


def gather_urls(args: argparse.Namespace) -> List[str]:
    urls: List[str] = []
    if args.urls:
        urls.extend([u.strip() for u in args.urls if u.strip()])
    if args.input:
        urls.extend(_read_urls_from_file(args.input))
    if args.csv:
        urls.extend(_read_urls_from_csv(args.csv, args.csv_column))
    if args.stdin:
        urls.extend(_read_urls_from_stdin())
    if not urls and not sys.stdin.isatty():
        urls.extend(_read_urls_from_stdin())
    if not urls:
        raise SystemExit("No URLs were provided")
    return _deduplicate(urls)


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    urls = gather_urls(args)
    extractor = NoteExtractor(timeout=args.timeout, user_agent=args.user_agent)

    notes: List[NoteData] = []
    failures: List[str] = []
    for url in urls:
        try:
            notes.append(extractor.extract(url))
        except ExtractionError as exc:
            failures.append(f"{url}: {exc}")

    if notes and not args.no_table:
        print(_render_markdown_table(notes))

    if args.export:
        for target in args.export:
            fmt, path = _parse_export_arg(target)
            _export(fmt, Path(path), notes)

    if failures:
        sys.stderr.write("\n".join(failures) + "\n")
        return 1
    return 0


def _parse_export_arg(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise SystemExit("Export arguments must be in the format FORMAT:PATH")
    fmt, path = value.split(":", 1)
    fmt = fmt.lower()
    if fmt not in {"csv", "tsv", "json", "md", "markdown"}:
        raise SystemExit(f"Unsupported export format: {fmt}")
    return fmt, path


def _export(fmt: str, path: Path, notes: Sequence[NoteData]) -> None:
    if fmt == "csv":
        notes_to_csv(str(path), notes)
    elif fmt == "tsv":
        notes_to_tsv(str(path), notes)
    elif fmt in {"md", "markdown"}:
        path.write_text(_render_markdown_table(notes), encoding="utf-8")
    elif fmt == "json":
        _write_json(path, notes)
    else:  # pragma: no cover - guard for future
        raise SystemExit(f"Unsupported export format: {fmt}")


if __name__ == "__main__":
    raise SystemExit(run())
