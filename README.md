# CSV repair and JSON conversion (DataGuard CSV Doctor)

Ingests CSV text, sanitizes common encoding and invisible-character issues, optionally auto-detects delimiters, repairs structural problems where possible, infers column types, and emits a JSON array of objects plus a structured diagnostic report.

## Why it exists

CSV is the default interchange format and often arrives with inconsistent columns, duplicated headers, placeholder “empty” tokens, and messy encodings. This tool is defensive: it repairs what it can, quarantines what it rejects, and explains both in `findings` and `stats`.

## How to run

**CLI** (from this directory, with Python 3.10+):

```bash
python csv_converter.py --file path/to/data.csv --output out.json
```

| Flag | Description |
|------|-------------|
| `--file` / `-f` | Input CSV path (**required**) |
| `--output` / `-o` | Output JSON path (default: `output.json`) |
| `--delimiter` / `-d` | `auto` (default), `,`, `;`, `|`, or `tab` |
| `--strict` | Reject rows with short/long column counts instead of padding or `_overflow` |
| `--quarantine PATH` | Write rejected rows as CSV (same delimiter as the parse) |
| `--no-types` | Skip type casting; keep cell values as strings |
| `--report` | Print stats, metadata, column profiles, warnings, and findings to stdout |

Reading the input file uses UTF-8. Failures to open or read the file exit with code `1` and raise an `errors.InputError`-style message on stderr.

**Library API**

```python
import csv_converter

result = csv_converter.run(csv_text, {
    "source_name": "optional label for findings",
    "delimiter": "auto",   # or ",", ";", "|", "tab"
    "strict": False,
    "no_types": False,
})
# result["output"]     # JSON string
# result["rows"]       # list[dict]
# result["findings"]   # list of diagnostic dicts
# result["stats"]      # counts and rates
# result["column_profiles"]  # name, inferred type, completeness %
```

## Features (what the code actually does)

### Input sanitization

Handled by `string_sanitizer.py` before CSV parsing: UTF-8 BOM, control characters (except newline/tab), Unicode whitespace, smart quotes, zero-width characters, ANSI escapes, and common mojibake hints. Each fix can append to `findings`.

### Delimiter detection

Counts `,`, `;`, `\t`, and `|` on the first 10 non-empty lines. The delimiter with the highest total wins. **Ties** break in order: comma → semicolon → tab → pipe. Confidence is `high` if the winner is at least 1.5× the runner-up, else `low`.

**Mixed-delimiter warnings** compare delimiters on **raw text lines** (not per parsed field). Commas inside quoted RFC 4180 fields can therefore produce occasional false positives.

### Headers

The first row is treated as a header if it is not all numeric and has at least one non-empty cell. **Duplicate header labels** are still treated as headers; `normalize_headers()` renames duplicates to `name_2`, `name_3`, etc. Empty header cells become `unnamed_column_N`.

### Row repair

- Expected width comes from the header row (or generated `column_N` names).
- Rows shorter than half the expected width are **rejected** and listed in `quarantine_rows`.
- Slightly short rows: padded with empty cells (unless `--strict`).
- Long rows: truncated to the header width; extra cells go under `_overflow` as a list (unless `--strict`).

### Empty cells

After trimming, these (case-insensitive) become JSON `null`: empty string, `n/a`, `null`, `-`, `--`, `none`, `na`.

### Type inference

Per column, if all non-empty values match boolean / integer / float patterns (including `,`, `$`, `%` stripping for numbers), that type is used. Otherwise the column stays string. When casting fails for a cell, that cell keeps its string value, `type_mismatches` increments, and a `type_mismatch` finding is added. There is **no** “90% rule”: every failed cast is reported.

### Output shape

- **`output`**: pretty-printed JSON (`indent=2`, `ensure_ascii=False`).
- **`stats`**: includes `rows_converted`, `rows_repaired`, `rows_rejected`, `rows_attempted`, `row_acceptance_rate_pct`, delimiter info, `mixed_delimiter_lines`, `type_mismatches`, etc.
- **`metadata`**: includes `delimiter` (repr), **`delimiter_char`** (actual separator character for tools), `header_status`, `source`.
- **`column_profiles`**: `name`, inferred `type`, `completeness` (% non-null) based on values **after** `clean_cell` and **before** type casting (null placeholders already applied).

### Parser

Tabular splitting uses Python’s **`csv.reader`** (`io.StringIO`), not a custom character-by-character state machine.

## Project layout

| File | Role |
|------|------|
| `csv_converter.py` | `run()`, CLI (`main`), delimiter/header/row/type logic |
| `string_sanitizer.py` | Pre-parse text cleanup and findings |
| `errors.py` | `InputError` and other shared exceptions (CLI uses `InputError` for unreadable files) |

## Development

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

Optional: `black`, `mypy` as listed in `requirements.txt`.

## Mega-app role

Intended as the tabular-ingest / “CSV doctor” step in a larger DataGuard-style pipeline: same contract as `run()` return value for downstream reporting or storage.
