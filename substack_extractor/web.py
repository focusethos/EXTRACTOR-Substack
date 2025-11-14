"""Simple Flask application for extracting Substack notes via a browser."""

from __future__ import annotations

import argparse
import csv
import io
import json
from typing import List, Optional, Sequence

from flask import Flask, Response, render_template_string, request

from .batch import BatchExtractor
from .cli import _render_markdown_table
from .extractor import NoteData, NoteExtractor

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Substack Note Extractor</title>
    <style>
      body { font-family: sans-serif; margin: 2rem; }
      textarea { width: 100%; min-height: 8rem; }
      input[type=text], input[type=number] { width: 100%; }
      table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
      th, td { border: 1px solid #ccc; padding: 0.5rem; vertical-align: top; }
      th { background: #f0f0f0; }
      .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; }
      .actions { display: flex; gap: 1rem; flex-wrap: wrap; margin-top: 1rem; }
      .errors { color: #b30000; margin-top: 1rem; }
      .failures { margin-top: 1rem; }
      .failures li { color: #b30000; }
      .hint { font-size: 0.9rem; color: #555; }
      @media (max-width: 600px) {
        body { margin: 1rem; }
      }
    </style>
  </head>
  <body>
    <h1>Substack Note Extractor</h1>
    <p class="hint">Paste note URLs or upload a file, then throttle the batch so Substack doesn&apos;t rate-limit you.</p>
    <form method="post" enctype="multipart/form-data">
      <h2>URLs</h2>
      <label for="urls">Paste URLs (one per line)</label>
      <textarea id="urls" name="urls">{{ urls|e }}</textarea>
      <label for="url_file">Or upload a text/CSV file with URLs</label>
      <input type="file" id="url_file" name="url_file" accept=".txt,.csv" />

      <h2>Rate limiting</h2>
      <div class="form-grid">
        <div>
          <label for="delay">Delay between requests (seconds)</label>
          <input type="number" step="0.1" id="delay" name="delay" value="{{ delay }}" />
        </div>
        <div>
          <label for="max_retries">Max retries per URL</label>
          <input type="number" id="max_retries" name="max_retries" value="{{ max_retries }}" />
        </div>
        <div>
          <label for="retry_backoff">Retry backoff multiplier</label>
          <input type="number" step="0.1" id="retry_backoff" name="retry_backoff" value="{{ retry_backoff }}" />
        </div>
      </div>

      <h2>HTTP settings</h2>
      <div class="form-grid">
        <div>
          <label for="timeout">Timeout (seconds)</label>
          <input type="number" id="timeout" name="timeout" value="{{ timeout }}" />
        </div>
        <div>
          <label for="user_agent">User agent (optional)</label>
          <input type="text" id="user_agent" name="user_agent" value="{{ user_agent|e }}" />
        </div>
      </div>

      <h2>Cookies</h2>
      <p class="hint">Provide one cookie header per line to rotate between requests. This is optional but can help avoid temporary blocks.</p>
      <textarea id="cookies" name="cookies">{{ cookies|e }}</textarea>
      <label for="cookie_file">Or upload a text file with one cookie header per line</label>
      <input type="file" id="cookie_file" name="cookie_file" accept=".txt" />

      <div class="actions">
        <button type="submit" name="action" value="preview">Extract</button>
        <button type="submit" name="action" value="download_csv">Download CSV</button>
        <button type="submit" name="action" value="download_tsv">Download TSV</button>
        <button type="submit" name="action" value="download_json">Download JSON</button>
        <button type="submit" name="action" value="download_markdown">Download Markdown</button>
      </div>
    </form>

    {% if errors %}
    <div class="errors">
      <h2>Issues</h2>
      <ul>
        {% for error in errors %}
        <li>{{ error }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}

    {% if notes %}
    <h2>Extracted notes</h2>
    <table>
      <thead>
        <tr>
          <th>URL</th>
          <th>Account</th>
          <th>Date</th>
          <th>Text</th>
          <th>Likes</th>
          <th>Comments</th>
          <th>Restacks</th>
          <th>Has image</th>
          <th>Has video</th>
        </tr>
      </thead>
      <tbody>
        {% for note in notes %}
        <tr>
          <td><a href="{{ note.url }}" target="_blank" rel="noopener">{{ note.url }}</a></td>
          <td>{{ note.account_name or '' }}</td>
          <td>{{ note.date_posted or '' }}</td>
          <td style="white-space: pre-wrap;">{{ note.text }}</td>
          <td>{{ note.likes if note.likes is not none else '' }}</td>
          <td>{{ note.comments if note.comments is not none else '' }}</td>
          <td>{{ note.restacks if note.restacks is not none else '' }}</td>
          <td>{{ 'Yes' if note.has_image else 'No' }}</td>
          <td>{{ 'Yes' if note.has_video else 'No' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}

    {% if failures %}
    <div class="failures">
      <h2>Failed URLs</h2>
      <ul>
        {% for failure in failures %}
        <li>{{ failure }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
  </body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def index() -> Response:
        errors: List[str] = []
        notes: List[NoteData] = []
        failures: List[str] = []

        urls_input = request.form.get("urls", "")
        cookies_input = request.form.get("cookies", "")
        delay_value = request.form.get("delay") or "0"
        max_retries_value = request.form.get("max_retries") or "3"
        retry_backoff_value = request.form.get("retry_backoff") or "2"
        timeout_value = request.form.get("timeout") or "30"
        user_agent = request.form.get("user_agent", "")
        action = request.form.get("action", "preview")

        delay = _parse_float(delay_value, 0.0, "Delay must be a number", errors)
        max_retries = _parse_int(max_retries_value, 3, "Max retries must be a positive integer", errors)
        retry_backoff = _parse_float(retry_backoff_value, 2.0, "Retry backoff must be a number", errors)
        timeout = _parse_int(timeout_value, 30, "Timeout must be a positive integer", errors)

        urls: List[str] = []
        cookies: List[str] = []

        if request.method == "POST" and not errors:
            urls.extend(_split_lines(urls_input))
            urls.extend(_read_urls_from_file_storage(request.files.get("url_file")))
            urls = _deduplicate(urls)
            if not urls:
                errors.append("Provide at least one Substack note URL.")

            cookies.extend(_split_lines(cookies_input))
            cookies.extend(_read_cookies_from_file_storage(request.files.get("cookie_file")))

            if not errors and urls:
                extractor = NoteExtractor(timeout=timeout, user_agent=user_agent or None)
                batch = BatchExtractor(
                    extractor,
                    delay=delay,
                    max_retries=max(max_retries, 1),
                    retry_backoff=max(retry_backoff, 1.0),
                    cookies=cookies,
                )
                notes, failures = batch.extract_all(urls)

                if action.startswith("download"):
                    fmt = action.split("_", 1)[1]
                    return _build_download_response(notes, fmt)

        return Response(
            render_template_string(
                HTML_TEMPLATE,
                urls=urls_input,
                cookies=cookies_input,
                delay=delay_value,
                max_retries=max_retries_value,
                retry_backoff=retry_backoff_value,
                timeout=timeout_value,
                user_agent=user_agent,
                notes=notes,
                failures=failures,
                errors=errors,
            )
        )

    return app


def _split_lines(value: str) -> List[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _deduplicate(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _read_urls_from_file_storage(storage) -> List[str]:
    if storage is None or not storage.filename:
        return []
    data = storage.read()
    if not data:
        return []
    text = data.decode("utf-8", errors="replace")
    if storage.filename.lower().endswith(".csv"):
        buffer = io.StringIO(text)
        reader = csv.reader(buffer)
        urls = [row[0].strip() for row in reader if row and row[0].strip()]
    else:
        urls = _split_lines(text)
    return urls


def _read_cookies_from_file_storage(storage) -> List[str]:
    if storage is None or not storage.filename:
        return []
    data = storage.read()
    if not data:
        return []
    text = data.decode("utf-8", errors="replace")
    return _split_lines(text)


def _parse_float(value: str, default: float, error_message: str, errors: List[str]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(error_message)
        return default


def _parse_int(value: str, default: int, error_message: str, errors: List[str]) -> int:
    try:
        parsed = int(value)
        if parsed < 0:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        errors.append(error_message)
        return default


def _build_download_response(notes: Sequence[NoteData], fmt: str) -> Response:
    fmt = fmt.lower()
    content: str
    mimetype: str
    extension: str
    if fmt == "csv":
        content = _serialise_tabular(notes, delimiter=",", include_header=True)
        mimetype = "text/csv; charset=utf-8"
        extension = "csv"
    elif fmt == "tsv":
        content = _serialise_tabular(notes, delimiter="\t", include_header=True)
        mimetype = "text/tab-separated-values; charset=utf-8"
        extension = "tsv"
    elif fmt == "json":
        content = json.dumps([note.to_dict() for note in notes], indent=2, ensure_ascii=False)
        mimetype = "application/json; charset=utf-8"
        extension = "json"
    elif fmt == "markdown":
        content = _render_markdown_table(notes)
        mimetype = "text/markdown; charset=utf-8"
        extension = "md"
    else:
        content = _render_markdown_table(notes)
        mimetype = "text/plain; charset=utf-8"
        extension = "txt"

    response = Response(content)
    response.headers["Content-Type"] = mimetype
    response.headers["Content-Disposition"] = f"attachment; filename=notes.{extension}"
    return response


def _serialise_tabular(notes: Sequence[NoteData], *, delimiter: str, include_header: bool) -> str:
    buffer = io.StringIO()
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
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=delimiter, quoting=csv.QUOTE_ALL)
    if include_header:
        writer.writeheader()
    for note in notes:
        writer.writerow(note.to_dict())
    return buffer.getvalue()


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Substack extractor web app")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args(argv)

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":  # pragma: no cover - manual usage entry point
    main()

