# Substack Note Extractor

This repository provides utilities that turn one or more Substack Note URLs into
structured tables. The extractor collects the account name, publication date,
body text, engagement counts (likes, comments, restacks) and whether the note
embeds images or videos. Results are rendered as a Markdown table by default and
can be exported to CSV, TSV, JSON or Markdown files for further analysis. A
browser-friendly interface is also available for people who prefer not to use
the command line.

## Installation

The project targets Python 3.11 or newer. Install the dependencies and invoke
the tools with Python:

```bash
python -m pip install -r requirements.txt
```

## Usage

You can pass URLs directly on the command line, read them from a text file,
pipe them through standard input, or supply a CSV file that contains the URLs.
The CLI now supports throttling large batches and rotating multiple cookie
headers to avoid Substack rate limiting.

```bash
# Extract two notes and show a Markdown table
python -m substack_extractor.cli --urls https://example.substack.com/p/note1 https://example.substack.com/p/note2

# Read URLs from a text file and export to CSV and Markdown
python -m substack_extractor.cli --input urls.txt --export csv:notes.csv --export md:notes.md

# Use a CSV file (takes the first column by default)
python -m substack_extractor.cli --csv links.csv --csv-column note_url

# Slow down large batches and rotate cookies
python -m substack_extractor.cli \
    --input urls.txt \
    --delay 2.5 \
    --max-retries 4 \
    --retry-backoff 1.5 \
    --cookie "sessionid=abc123" \
    --cookie-file cookies.txt
```

When an export path is provided, multi-line note content is wrapped in quotes so
that spreadsheet tools preserve the original formatting, including bullet
lists.

## Browser interface

Launch a local web server when you would rather paste URLs into a form and
download the results straight from your browser:

```bash
python -m substack_extractor.web --host 0.0.0.0 --port 8000
```

The web UI mirrors the CLI options: paste or upload URLs, configure the delay,
retry budget, and optional cookie headers, then export to CSV/TSV/JSON/Markdown
without leaving the page.

## Testing

Run the unit test suite with:

```bash
python -m unittest discover -s tests
```

The tests rely on in-memory HTML snippets so they do not require network access
and can be executed in offline environments.
