# Substack Note Extractor

This repository provides a lightweight command line utility that turns one or more
Substack Note URLs into a structured table. The extractor collects the account
name, publication date, body text, engagement counts (likes, comments, restacks)
and whether the note embeds images or videos. Results are rendered as a
Markdown table by default and can be exported to CSV, TSV, JSON or Markdown
files for further analysis.

## Installation

The project has no third-party dependencies and runs on Python 3.11 or newer.
Clone the repository and invoke the CLI with `python -m substack_extractor.cli`.

## Usage

You can pass URLs directly on the command line, read them from a text file,
pipe them through standard input, or supply a CSV file that contains the URLs.

```bash
# Extract two notes and show a Markdown table
python -m substack_extractor.cli --urls https://example.substack.com/p/note1 https://example.substack.com/p/note2

# Read URLs from a text file and export to CSV and Markdown
python -m substack_extractor.cli --input urls.txt --export csv:notes.csv --export md:notes.md

# Use a CSV file (takes the first column by default)
python -m substack_extractor.cli --csv links.csv --csv-column note_url
```

When an export path is provided, multi-line note content is wrapped in quotes so
that spreadsheet tools preserve the original formatting, including bullet
lists.

## Testing

Run the unit test suite with:

```bash
python -m unittest discover -s tests
```

The tests rely on in-memory HTML snippets so they do not require network access
and can be executed in offline environments.
