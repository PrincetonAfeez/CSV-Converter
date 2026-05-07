# Architecture Decision Record
## App 04 — CSV Converter
**DataGuard Group | Document 1 of 5**
**Status: Accepted**

---

## Context

DataGuard processes data files that arrive as CSV. In practice, "CSV" is a loosely defined format — files arrive with different delimiters (comma, semicolon, pipe, tab), inconsistent quoting, missing headers, empty column names, duplicate column names, rows with too few or too many fields, null placeholder strings like "N/A" and "none", and numbers formatted with currency symbols or percent signs. The CSV Converter (App 04) is responsible for repairing all of these issues and converting the result to structured JSON with inferred types. Downstream apps receive clean, typed dictionaries rather than raw string rows.

---

## Decisions

### Decision 1 — Auto-detect delimiter with explicit tie-breaking

**Chosen:** `detect_delimiter()` counts occurrences of `,`, `;`, `\t`, `|` in the first 10 non-empty lines. The highest-count delimiter wins. On ties, a fixed preference order (`comma > semicolon > tab > pipe`) resolves the winner.

**Rejected:** Requiring the caller to always specify the delimiter.

**Reason:** Most callers do not know or should not need to know the delimiter of their input files. The auto-detection handles the common case correctly. The tie-break preference order encodes regional defaults — comma is the most globally common, semicolon is common in European locales where comma is the decimal separator. Confidence (`"high"` vs `"low"`) is reported in stats so callers can detect ambiguous inputs.

---

### Decision 2 — Repair-first with `strict` opt-in

**Chosen:** By default, short rows are padded with empty strings and long rows are truncated (extra columns moved to `_overflow`). With `strict=True`, both are rejected to quarantine instead.

**Rejected:** Reject all malformed rows by default.

**Reason:** Real CSV files frequently have minor structural inconsistencies — a trailing blank field, an extra comma from an export bug. Silently dropping these rows would lose data without explanation. Repairing and flagging preserves data while documenting what was done. Callers who require exact structural integrity can opt into `strict` mode.

---

### Decision 3 — Type inference at the column level

**Chosen:** `detect_type()` analyzes all values in a column together and assigns a type (`boolean`, `integer`, `float`, `string`, `empty`). `convert_value()` applies the inferred type to each cell.

**Rejected:** Per-cell type guessing.

**Reason:** Per-cell guessing produces inconsistent types within a column — one row has an integer, the next a string, depending on whether a value happens to look numeric. Column-level inference requires all non-null values to agree on a type before conversion is applied, producing homogeneous typed columns. The `no_types` flag lets callers skip this entirely when they need raw strings.

---

### Decision 4 — `EMPTY_CELL_VALUES` normalization to `None`

**Chosen:** `clean_cell()` checks against a set of common null placeholders (`{"", "n/a", "null", "-", "--", "none", "na"}`) and returns `None` for matches.

**Rejected:** Leaving placeholder strings as-is.

**Reason:** Downstream apps that receive `"N/A"` in a numeric column will fail type conversion. Normalizing these to `None` makes them type-safe and distinguishable from intentional empty strings. The full set was chosen based on the most common real-world null representations encountered in exported data.

---

### Decision 5 — Quarantine rows as a separate output

**Chosen:** Rejected rows are collected in `result["quarantine_rows"]` and can be written to a separate CSV file via `write_quarantine_csv()`.

**Rejected:** Simply discarding rejected rows or including them as errors in the main output.

**Reason:** Rejected rows still contain data. An operator may want to manually review and re-process them. Providing a separate quarantine file makes this possible without the operator needing to reconstruct which rows were rejected from the findings log.

---

### Decision 6 — Column profiles in the result

**Chosen:** `result["column_profiles"]` contains `{"name", "type", "completeness"}` for every header. Completeness is the percentage of non-null values in the column.

**Rejected:** Reporting only per-row stats.

**Reason:** Column-level insight is more useful than row-level insight for data quality assessment. A column that is 30% complete is a data quality problem. Knowing which column has type `empty` signals a dead column in the source. These profiles give the DataGuard bootstrapper the information it needs to decide whether to proceed with downstream processing.

---

### Decision 7 — Mixed delimiter detection scan

**Chosen:** The first 100 lines are scanned for "delimiter drift" — lines where a different character appears more frequently than the detected primary delimiter.

**Rejected:** Not checking for delimiter inconsistency.

**Reason:** Mixed delimiter files are a common source of silent parsing errors. A file that is mostly comma-separated but has a few pipe-separated lines will parse those lines as a single-field row. Surfacing these as `mixed_delimiter` findings gives the caller early warning before the downstream data is affected.

---

## Consequences

**Positive:**
- Auto-detection + repair handles the most common real-world CSV problems without caller intervention.
- Column profiles provide a data quality signal beyond simple row counts.
- Quarantine rows preserve rejected data for review.
- `strict` mode provides a strict validation path when repair is not desired.
- `no_types` mode supports callers that need raw strings (e.g., when the caller performs its own type coercion).

**Negative / Trade-offs:**
- Type inference reads the entire column before applying conversions — the full dataset is held in memory. For very large files, streaming type inference would be needed.
- The `looks_like_header()` heuristic is not perfect. A CSV where the first row happens to be all-string data and the remaining rows are numeric will incorrectly identify the first data row as a header. The `test_looks_like_header_accepts_duplicate_column_names` test validates a specific edge case but not the full space of ambiguous inputs.
- Overflow values go to `_overflow` key — this is a convention, not a standard. Downstream apps that expect exact column schemas need to be aware of this.

---

*Constitution reference: Articles 1, 2, 3. Amendment 1.3: `string_sanitizer.py` is a pinned snapshot. Bug fixed during evaluation: missing `errors.py` added before documentation.*


---


# Technical Design Document
## App 04 — CSV Converter
**DataGuard Group | Document 2 of 5**

---

## Overview

CSV Converter takes raw CSV text, repairs structural problems, infers column types, and outputs a JSON array of typed dictionaries. It is the fourth module in the DataGuard group, sitting upstream of the Analyzer and downstream of String Sanitizer (which it calls internally).

**File:** `csv_converter.py` (530 lines)
**Supporting:** `errors.py` (shared), `string_sanitizer.py` (pinned snapshot)
**Entry points:** `run()` (public API), `main()` (CLI)
**Dependencies:** `re`, `csv`, `io`, `json`, `argparse`, `sys`, `collections.Counter`, `pathlib` (stdlib); `string_sanitizer`, `errors` (DataGuard)

---

## Data Flow

```
Input CSV text (str)
        │
        ▼
string_sanitizer.run()
        │  cleaned text + sanitizer findings
        ▼
detect_delimiter(lines)          → delimiter: str, confidence: str
        │
        ▼
parse_csv_rows(cleaned_text, delimiter)  → raw_rows: list[list[str]]
        │
        ├─ Mixed delimiter scan (first 100 lines)
        │
        ├─ looks_like_header(first_row)
        │     ├─ True  → normalize_headers(first_row) → headers, header_findings
        │     └─ False → generate column_N headers
        │
        └─ For each data row:
               ├─ Length check → reject / pad / truncate
               ├─ clean_cell() on each value → None or trimmed str
               └─ Build row_dict with overflow handling
        │
        ▼
Column-level type inference:
  detect_type(column_values)    → inferred_types: dict[str, str]
  convert_value(value, type)    → typed value
        │
        ▼
Completeness calculation per column
        │
        ▼
json.dumps(converted_rows)      → output_json: str
        │
        ▼
Standard DataGuard result dict
  + quarantine_rows
  + column_profiles
```

---

## Module-Level Constants

### `DELIMITER_LABELS`
```python
{"auto": None, ",": ",", ";": ";", "|": "|", "tab": "\t"}
```
Maps CLI-friendly delimiter names to actual characters. `"auto"` triggers detection.

### `EMPTY_CELL_VALUES`
```python
{"", "n/a", "null", "-", "--", "none", "na"}
```
Lowercased null placeholder strings. `clean_cell()` checks against this set after stripping whitespace.

---

## Function Reference

### `detect_delimiter(lines: list[str]) -> tuple[str, str]`
Counts `,`, `;`, `\t`, `|` occurrences in the first 10 non-empty lines. Returns `(best_delimiter, confidence)`.

- **Tie-breaking:** fixed order `[",", ";", "\t", "|"]` — first in list wins on equal count
- **Confidence:** `"high"` if winner count ≥ 1.5× runner-up; `"low"` otherwise; `"manual"` if caller specified

---

### `looks_like_header(row: list[str]) -> bool`
Returns `False` if:
- Row is empty
- All non-empty cells match `r"-?\d+(?:\.\d+)?"` (pure numbers)

Returns `True` if any cell has non-empty content. Duplicate labels are accepted — `normalize_headers()` handles de-duplication.

---

### `normalize_headers(header_row: list[str]) -> tuple[list[str], list[dict]]`
Processes each header in order:
1. Strips whitespace — logs `"header_trim"` finding if changed
2. Fills blank headers with `unnamed_column_N` — logs `"header_repair"` finding
3. Tracks duplicates via `Counter`; appends `_N` suffix on second+ occurrence — logs `"duplicate_header"` finding

Returns `(normalized_headers, findings)`.

---

### `parse_csv_rows(text: str, delimiter: str) -> list[list[str]]`
Wraps `csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)`. Handles all standard CSV quoting conventions.

---

### `clean_cell(value: str) -> str | None`
1. Strips leading/trailing whitespace
2. Lowercases and checks against `EMPTY_CELL_VALUES`
3. Returns `None` for null placeholders, trimmed string otherwise

---

### `detect_type(values: list[str | None]) -> str`
Filters out `None` and `""` before type testing. Returns the first matching type:

| Type | Pattern |
|---|---|
| `"empty"` | No non-null values |
| `"boolean"` | All values in `{"true","false","yes","no","1","0","y","n"}` |
| `"integer"` | All values match `r"-?\d+"` |
| `"float"` | All values match `r"-?\d+(?:\.\d+)?%?"` after stripping `,` and `$` |
| `"string"` | Default fallback |

---

### `convert_value(value: str | None, target_type: str)`
Returns `None` for `None` input. Type conversions:
- `"boolean"` → `True` if value in `{"true","yes","1","y"}`
- `"integer"` → `int(value.replace(",","").replace("$",""))`
- `"float"` → `float(value.replace(",","").replace("$","").rstrip("%"))`
- `"string"` / `"empty"` → value unchanged

Raises `ValueError` on failed conversion — caller logs `"type_mismatch"` finding.

---

### `run(input_text: str, config: dict | None = None) -> dict`
Main pipeline. Config keys:

| Key | Type | Default | Description |
|---|---|---|---|
| `delimiter` | `str` | `"auto"` | `"auto"`, `","`, `";"`, `"\|"`, `"tab"` |
| `strict` | `bool` | `False` | Reject malformed rows instead of repairing |
| `no_types` | `bool` | `False` | Skip type inference, keep strings |
| `source_name` | `str` | `"<input>"` | Label for metadata |

Returns a result dict with additional keys beyond the standard DataGuard envelope:
- `"rows"` — `list[dict]` of converted row objects
- `"quarantine_rows"` — `list[list[str]]` of rejected raw rows
- `"column_profiles"` — `list[dict]` with `name`, `type`, `completeness`

---

### `write_quarantine_csv(path: Path, rows: list[list[str]], delimiter: str) -> None`
Writes rejected rows to a CSV file using the same delimiter as the input. Pads shorter rows to the maximum row width.

---

### `print_report(result: dict) -> None`
Formats and prints a human-readable report to stdout. Includes title, summary, stats, metadata, column profiles, warnings, and up to 200 findings.

---

### `main(argv: list[str] | None = None) -> int`
CLI entry point. Returns 0 on success, 1 on file read error.

Flags: `--file` (required), `--output`, `--delimiter`, `--strict`, `--quarantine`, `--no-types`, `--report`.

---

## Row Repair Logic

| Condition | Default behavior | `strict=True` |
|---|---|---|
| Row length < half expected | Reject to quarantine | Reject to quarantine |
| Row length < expected | Pad with empty strings | Reject to quarantine |
| Row length > expected | Truncate; extras → `_overflow` | Reject to quarantine |
| Row length == expected | Pass through | Pass through |

The "less than half expected" case is always rejected regardless of strict mode — rows that short cannot be reliably repaired.

---

## Finding Categories

| Category | Severity | Description |
|---|---|---|
| `header_trim` | low | Whitespace stripped from header |
| `header_repair` | low | Empty header filled with `unnamed_column_N` |
| `duplicate_header` | low | Duplicate header renamed with `_N` suffix |
| `missing_header` | medium | First row was not a header; generic names generated |
| `mixed_delimiter` | low | Line uses different delimiter than detected primary |
| `row_padding` | low | Short row padded to match header count |
| `row_overflow` | low | Extra columns moved to `_overflow` |
| `rejected_row` | medium | Row too short to repair |
| `strict_rejection` | medium | Row rejected by strict mode |
| `type_mismatch` | low | Cell value failed inferred type conversion |


---


# Interface Design Specification
## App 04 — CSV Converter
**DataGuard Group | Document 3 of 5**

---

## Public API

### Primary Entry Point

```python
run(input_text: str, config: dict | None = None) -> dict
```

**Config keys:**

| Key | Type | Default | Description |
|---|---|---|---|
| `delimiter` | `str` | `"auto"` | `"auto"`, `","`, `";"`, `"\|"`, `"tab"` |
| `strict` | `bool` | `False` | Reject malformed rows instead of repairing |
| `no_types` | `bool` | `False` | Keep all values as strings |
| `source_name` | `str` | `"<input>"` | Label for result metadata |

---

### CLI

```bash
# Basic conversion (auto-delimiter, auto-type inference)
python csv_converter.py --file data.csv --output result.json

# Strict mode — reject any malformed rows
python csv_converter.py --file data.csv --strict --quarantine rejected.csv

# Manual delimiter
python csv_converter.py --file data.csv --delimiter ";"

# No type inference
python csv_converter.py --file data.csv --no-types

# Full diagnostic report printed to stdout
python csv_converter.py --file data.csv --report

# Module invocation
python -m csv_converter --file data.csv
```

Exit codes: `0` success, `1` file read error.

---

## Result Envelope

```python
{
    "module_name": "csv",
    "title": "DataGuard CSV Doctor Report",
    "output": str,                  # JSON string of converted rows
    "rows": list[dict],             # Typed row dicts
    "quarantine_rows": list[list],  # Raw rejected rows
    "findings": list[dict],
    "warnings": list[str],          # Empty or ["N rows were rejected."]
    "errors": [],
    "stats": dict,
    "metadata": dict,
    "column_profiles": list[dict],
    "summary": str,
}
```

---

## Stats Schema

```python
{
    "rows_converted": int,
    "rows_repaired": int,
    "rows_rejected": int,
    "rows_attempted": int,
    "row_acceptance_rate_pct": float,
    "delimiter": str,               # repr() form, e.g. "','"
    "delimiter_confidence": str,    # "high", "low", or "manual"
    "header_status": str,           # "provided" or "generated"
    "expected_columns": int,
    "mixed_delimiter_lines": int,
    "type_mismatches": int,
}
```

---

## Column Profile Schema

```python
[
    {
        "name": str,          # Header name (after normalization)
        "type": str,          # "boolean" | "integer" | "float" | "string" | "empty"
        "completeness": float # % of non-null values, e.g. 97.3
    },
    ...
]
```

---

## Input/Output Examples

### Simple CSV
```python
run("a,b\n1,2\n3,4\n")
# output (JSON): [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
# stats["rows_converted"]: 2
# stats["row_acceptance_rate_pct"]: 100.0
# column_profiles: [{"name":"a","type":"integer","completeness":100.0}, ...]
```

### Short row padding (default)
```python
run("a,b,c\n1,2\n")
# row becomes {"a": 1, "b": 2, "c": None}
# findings: [{"category": "row_padding", ...}]
# stats["rows_repaired"]: 1
```

### Short row rejection (strict mode)
```python
run("a,b,c\n1,2\n", {"strict": True})
# rows: []
# quarantine_rows: [["1", "2"]]
# stats["rows_rejected"]: 1
```

### Null placeholder normalization
```python
run("name,score\nAlice,N/A\nBob,85\n")
# rows: [{"name": "Alice", "score": None}, {"name": "Bob", "score": 85}]
```

### No type inference
```python
run("a,b\n1,2\n", {"no_types": True})
# rows: [{"a": "1", "b": "2"}]
```

### Duplicate headers
```python
run("Name,Name,Age\nAlice,Smith,30\n")
# headers: ["Name", "Name_2", "Age"]
# findings: [{"category": "duplicate_header", ...}]
```

### Generated headers (no header row)
```python
run("1,2,3\n4,5,6\n")
# headers: ["column_1", "column_2", "column_3"]
# stats["header_status"]: "generated"
```

### Overflow columns
```python
run("a,b\n1,2,3,4\n")
# rows: [{"a": 1, "b": 2, "_overflow": [3, 4]}]
# findings: [{"category": "row_overflow", ...}]
```

### Boolean column
```python
run("active\nyes\nno\nyes\n")
# rows: [{"active": True}, {"active": False}, {"active": True}]
# column_profiles: [{"name":"active","type":"boolean",...}]
```

---

## Delimiter Auto-Detection

| Input | Detected | Confidence |
|---|---|---|
| `"a,b,c\n1,2,3"` | `,` | high |
| `"a;b;c\n1;2;3"` | `;` | high |
| `"a,b\|c\n1,2\|3"` | `,` | low (tie broken by preference) |
| `"a\tb\tc\n1\t2\t3"` | `\t` | high |


---


# Runbook
## App 04 — CSV Converter
**DataGuard Group | Document 4 of 5**

---

## Requirements

- Python 3.10 or later
- No third-party dependencies
- `errors.py` and `string_sanitizer.py` must be in the same directory or on `PYTHONPATH`

---

## Installation

```bash
git clone https://github.com/PrincetonAfeez/CSV-Converter
cd CSV-Converter
```

Confirm `errors.py` and `string_sanitizer.py` are present. No `pip install` required.

---

## Running the CLI

### Basic conversion
```bash
python csv_converter.py --file data.csv --output result.json
```

### Strict mode with quarantine file
```bash
python csv_converter.py --file data.csv --strict --quarantine rejected.csv
```

### Manual delimiter (semicolons)
```bash
python csv_converter.py --file european.csv --delimiter ";"
```

### Tab-delimited
```bash
python csv_converter.py --file data.tsv --delimiter tab
```

### No type inference (keep strings)
```bash
python csv_converter.py --file data.csv --no-types --output raw.json
```

### Full diagnostic report to stdout
```bash
python csv_converter.py --file data.csv --report
```

### Module invocation
```bash
python -m csv_converter --file data.csv
```

---

## Using as a Library

### Basic conversion
```python
from csv_converter import run

result = run(csv_text, {"source_name": "import.csv"})
rows = result["rows"]         # list of typed dicts
print(result["summary"])
```

### Inspect column profiles
```python
for profile in result["column_profiles"]:
    print(f"{profile['name']}: {profile['type']} ({profile['completeness']}% complete)")
```

### Handle quarantined rows
```python
from csv_converter import run, write_quarantine_csv
from pathlib import Path

result = run(csv_text, {"strict": True})
if result["quarantine_rows"]:
    write_quarantine_csv(Path("quarantine.csv"), result["quarantine_rows"], ",")
    print(f"{len(result['quarantine_rows'])} rows quarantined.")
```

### Check for delimiter confidence
```python
result = run(csv_text)
if result["stats"]["delimiter_confidence"] == "low":
    print("Warning: delimiter detection was ambiguous. Consider specifying manually.")
```

### Use `no_types` for custom type handling
```python
result = run(csv_text, {"no_types": True})
# All values are strings — apply your own coercion
for row in result["rows"]:
    row["price"] = float(row["price"].replace("$", ""))
```

---

## Running Tests

```bash
pip install pytest
pytest test_csv_converter.py -v
```

### Run specific tests
```bash
pytest test_csv_converter.py -v -k "delimiter"
pytest test_csv_converter.py -v -k "strict"
pytest test_csv_converter.py -v -k "cli"
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'string_sanitizer'` or `'errors'`
Both files must be in the same directory as `csv_converter.py`. Set `PYTHONPATH` if needed.

### Wrong delimiter detected
Use `--delimiter` to specify explicitly: `--delimiter ";"`, `--delimiter "|"`, `--delimiter tab`.

### Numbers staying as strings
Check `stats["header_status"]` — if `"generated"`, the first row was treated as data. Also verify no mixed types exist in the column (e.g., a mix of integers and strings forces `"string"` type).

### Overflow data in `_overflow` column
Some rows had more fields than the header. The extra values are preserved in `_overflow`. Use `--strict` to reject these rows instead, or preprocess the file to fix the structural mismatch.

### Empty column in profiles
A column with `"type": "empty"` has no non-null values after `clean_cell()` processing. Check if all values in that column are null placeholders (`N/A`, `none`, etc.).

### Quarantine rows not written
`--quarantine` requires a file path argument. The parent directory must be writable.


---


# Lessons Learned
## App 04 — CSV Converter
**DataGuard Group | Document 5 of 5**

---

## Why This Design Was Chosen

The "repair-first" philosophy came from thinking about what the DataGuard pipeline actually needs. If the CSV Converter rejected every malformed row, the Contact Extractor and Analyzer downstream would receive less data than expected. Repairing the common cases — padding, truncation — means more data flows through the pipeline. The `strict` opt-in preserves the ability to enforce exact structural requirements when needed.

Column-level type inference rather than cell-level was a deliberate design choice that took two versions to arrive at. The first version tried to infer types per-cell, which produced mixed-type columns — a column that was 99% integers but had one empty cell would be treated as mixed. Moving to column-level inference (all non-null values must agree) produced homogeneous output that downstream apps could rely on.

---

## What Was Intentionally Omitted

**Date/datetime detection:** Dates are left as strings. Reliable date parsing requires knowing the format (ISO 8601, US, European, epoch) and the locale, which varies widely across real files. Treating dates as strings is safe — the downstream app that uses the dates can apply the right parser for its context.

**Multi-line cell support beyond standard CSV quoting:** Python's `csv.reader` already handles RFC 4180 quoted multi-line values. Custom multi-line heuristics were not added — the stdlib handles this correctly.

**Large file streaming:** The entire file is read into memory before processing. For DataGuard's typical inputs this is not a problem. A generator-based streaming implementation would be needed for files with millions of rows.

**Encoding detection:** UTF-8 is assumed. Files in other encodings must be decoded by the caller before passing to `run()`.

---

## Biggest Weakness

The `looks_like_header()` heuristic fails on a CSV where the first data row happens to contain only string values and subsequent rows are numeric. For example:

```
Alice,Sales,New York
1200.50,38,2022
```

The first row looks like a header (non-numeric strings) but is actually data. There is no reliable general-purpose solution without external schema knowledge. The current heuristic documents this limitation and accepts that generated `column_N` headers are the safe fallback.

---

## Scaling Considerations

**If files grow to millions of rows:** Replace the list accumulation in `run()` with a generator that yields rows one at a time and writes JSON incrementally. The type inference stage would need to be separated into a first-pass (collect types) + second-pass (apply types) approach, or moved to a streaming schema-based approach where the caller provides expected types.

**If multiple delimiter types need to coexist:** The mixed delimiter detection already flags lines that appear to use a different delimiter. A future version could attempt to auto-split these lines with the detected alternate delimiter and merge them into the output.

**If type accuracy needs to improve:** The current `detect_type()` uses regex-based heuristics. Replacing it with a statistics-based sampler (analyze a random sample of 1000 values rather than all values) would improve performance at scale while maintaining accuracy for large homogeneous columns.

---

## What the Next Refactor Would Be

1. **Date type detection** — add `"date"` and `"datetime"` as `detect_type()` outputs with configurable format patterns.
2. **Streaming output** — yield JSON rows incrementally rather than accumulating.
3. **Column type hints in config** — allow callers to specify expected column types, overriding inference.
4. **`dataguard-common` package** — replace pinned `string_sanitizer.py` snapshot with a proper shared package.

---

## The Bug Fixed Before Documentation

During the evaluation session, `errors.py` was missing from the repository. `csv_converter.py` imports `InputError` from it inside `main()`, so the CLI would fail on import without the file. The fix was simply adding `errors.py` (the standard DataGuard shared exceptions file) to the repo. The lesson: confirm that all imports resolve before considering a module complete, even imports that appear only inside function bodies.

---

## What This Project Taught

**Repair is often better than reject.** The instinct when building a validator is to be strict — reject anything that doesn't conform. But in a data pipeline, strict rejection loses data. The `strict` mode exists for callers who genuinely need it, but the default is to repair and document, not discard.

**Column-level inference is the right grain for type detection.** The transition from per-cell to per-column inference was the most important architectural change in this module. It mirrors how real type systems work — a column has a type, not individual cells.

**Stats should tell the whole story.** The `row_acceptance_rate_pct`, `delimiter_confidence`, `header_status`, and `mixed_delimiter_lines` fields were added after reflecting on what an operator would want to know after running a conversion. Building the stats to answer the question "was this conversion reliable?" rather than just "how many rows did it process?" made the output genuinely useful.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation) for App 04.*
