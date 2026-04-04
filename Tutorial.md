# CSV Converter: build it from scratch

This guide rebuilds the current repository as a clean Python CLI + library project.

## 1) Decide the contract first
Before writing code, lock down the exact behavior:

- Input: raw CSV text or a CSV file path.
- Output: cleaned JSON rows plus diagnostics.
- Modes: auto delimiter detection, strict mode, optional type inference, optional quarantine file.
- Public API: `run(input_text: str, config: dict | None = None) -> dict`
- CLI entry: `python csv_converter.py --file input.csv --output output.json`

The best first deliverable is a schema for the result object. Use the schema file in `Schema/csv_converter_result.schema.json`.

## 2) Create the project structure
Use this layout:

```text
CSV-Converter/
├─ Schema/
│  └─ csv_converter_result.schema.json
├─ tests/
│  ├─ test_csv_converter.py
│  └─ test_string_sanitizer.py
├─ csv_converter.py
├─ string_sanitizer.py
├─ errors.py
├─ requirements.txt
├─ README.md
└─ .gitignore
```

## 3) Create the virtual environment
From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

## 4) Add development dependencies
For this repo, the runtime is standard-library only. Development tools are enough:

```txt
pytest>=7.0.0
black>=23.0.0
mypy>=1.0.0
```

Install them with:

```bash
pip install -r requirements.txt
```

## 5) Create `errors.py`
The current repo imports `InputError` in the CLI, so add this file first:

```python
class InputError(Exception):
    """Raised when the input file cannot be read."""
```

This prevents the CLI from failing on `from errors import InputError`.

## 6) Build `string_sanitizer.py`
Implement the sanitizer as a pure text-processing module.

### What it should do
- Remove UTF-8 BOM.
- Remove ANSI escape sequences.
- Remove control characters except newline and tab.
- Normalize Unicode whitespace to normal spaces.
- Normalize curly quotes to straight quotes.
- Remove zero-width characters.
- Return structured findings and stats.

### Suggested internal functions
- `build_tracked_characters(text)`
- `line_number_for_position(text, position)`
- `describe_character(character)`
- `add_character_finding(...)`
- `strip_bom(...)`
- `remove_ansi_codes(...)`
- `strip_control_chars(...)`
- `normalize_whitespace(...)`
- `normalize_smart_quotes(...)`
- `remove_zero_width(...)`
- `summarize_findings(findings)`
- `sanitize(text)`
- `build_result(cleaned_text, findings, stats, source_name)`
- `run(input_text, config=None)`

### Design rule
Keep it deterministic. The sanitizer should never guess structure. It should only clean text artifacts and report them.

## 7) Build `csv_converter.py`
This is the main domain module.

### Step 7.1: constants
Add:

- `DELIMITER_LABELS = {"auto": None, ",": ",", ";": ";", "|": "|", "tab": "\t"}`
- `EMPTY_CELL_VALUES = {"", "n/a", "null", "-", "--", "none", "na"}`

### Step 7.2: delimiter detection
Create `detect_delimiter(lines)`.

Logic:
- Inspect the first 10 non-empty lines.
- Count commas, semicolons, tabs, and pipes.
- Choose the highest count.
- Break ties in this order: comma, semicolon, tab, pipe.
- Return both the delimiter and a confidence level.

### Step 7.3: header detection
Create `looks_like_header(row)`.

Suggested rule:
- Empty row => not a header.
- If all populated cells are numeric-looking => probably not a header.
- Otherwise treat it as a header.

Then create `normalize_headers(header_row)`.

Rules:
- Trim whitespace.
- Replace blank headers with `unnamed_column_N`.
- Rename duplicates to `name_2`, `name_3`, and so on.
- Add findings for each repair.

### Step 7.4: CSV parsing
Use Python's built-in CSV reader:

```python
csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
```

Do not write a custom parser unless you truly need one.

### Step 7.5: cell cleanup
Create `clean_cell(value)`.

Rules:
- `strip()` whitespace.
- Convert placeholders like `N/A`, `null`, `-`, `--`, `none`, `na` to `None`.

### Step 7.6: type inference
Create:
- `detect_type(values)`
- `convert_value(value, target_type)`

Support:
- boolean
- integer
- float
- string
- empty

Keep inference conservative. A column should only become numeric or boolean if all non-null values match.

### Step 7.7: row repair and rejection
Inside `run()`:

1. Sanitize text with `string_sanitizer.run()`.
2. Detect or apply delimiter.
3. Parse rows.
4. Determine headers.
5. For each data row:
   - reject very short rows
   - pad slightly short rows unless `strict=True`
   - move extra cells into `_overflow` unless `strict=True`
   - record findings
6. Build normalized row dictionaries.
7. Infer types and cast values unless `no_types=True`.
8. Calculate completeness by column.
9. Build final stats, metadata, and summary.
10. Return a result object that matches the schema.

## 8) Add the CLI
In `csv_converter.py`, add `main(argv=None)`.

### CLI flags
- `--file`, `-f`: required input path
- `--output`, `-o`: output JSON path
- `--delimiter`, `-d`: `auto`, `,`, `;`, `|`, `tab`
- `--strict`
- `--quarantine PATH`
- `--no-types`
- `--report`

### CLI flow
- Read input file as UTF-8.
- On file read failure, raise or print `InputError` and return exit code `1`.
- Call `run()`.
- Write `result["output"]` to disk.
- If quarantine rows exist and the user supplied a quarantine path, write them as CSV.
- If `--report` is enabled, print a readable summary.

## 9) Add `write_quarantine_csv()`
This helper should:
- create parent directories if needed
- compute the widest quarantined row
- right-pad shorter rows with empty strings
- write rows with the same delimiter used during parsing

## 10) Add `print_report()`
Print these sections:
- title
- summary
- stats
- metadata
- column profiles
- warnings
- findings

Keep it readable JSON-style for now.

## 11) Write tests before polishing
Create `tests/test_csv_converter.py`.

Minimum tests:
- delimiter tie prefers comma
- duplicate headers are accepted and normalized
- null placeholders become `None`
- simple CSV converts to JSON rows
- strict mode rejects bad rows
- `no_types=True` keeps strings
- CLI writes output file
- missing input file returns exit code `1`

Also add `tests/test_string_sanitizer.py` with cases for:
- BOM removal
- ANSI removal
- NUL removal
- curly quote normalization
- zero-width character removal
- Unicode whitespace normalization

Run tests with:

```bash
python -m pytest tests/ -v
```

## 12) Validate against the schema
After `run()` returns a result, validate it against the schema during development.

A simple approach:
- add `jsonschema` only for development, or
- keep a fixture output and check required fields in tests.

This is optional for the first version, but strongly recommended.

## 13) Add sample files for manual testing
Create a `samples/` folder with:
- valid comma CSV
- semicolon CSV
- tab-delimited CSV
- file with BOM
- file with duplicate headers
- file with short rows
- file with long rows
- file with placeholder nulls
- file with messy Unicode spaces

That gives you fast regression checks.

## 14) Improve the README
Document:
- project purpose
- CLI usage
- Python version
- library API example
- schema contract
- sample output
- strict mode behavior
- quarantine behavior
- limitations

## 15) Package hardening pass
Once the app works, do this cleanup:

- move from a single-file script layout to a package layout if you want publishing
- add `pyproject.toml`
- add CI for `pytest`, `black --check`, and `mypy`
- add a schema validation test
- add better exception types
- separate parsing logic from reporting logic

## 16) Recommended fixes for the current repo
If you are improving the existing repo instead of rebuilding from zero, do these first:

1. Add the missing `errors.py` file.
2. Add tests for `string_sanitizer.py`.
3. Add schema validation tests for the `run()` result.
4. Split `csv_converter.py` into smaller modules when ready.
5. Add sample inputs and golden outputs.
6. Add CI.

## 17) Smoke test commands
Use these after implementation:

```bash
python csv_converter.py --file samples/basic.csv --output out.json --report
python csv_converter.py --file samples/bad_rows.csv --output out.json --quarantine quarantine/rejected.csv --report
python csv_converter.py --file samples/types.csv --output out.json --no-types
python -m pytest tests/ -v
```

## 18) Definition of done
You are done when:
- CLI reads CSV and writes valid JSON
- `run()` returns the documented result object
- output matches the schema
- sanitizer findings are preserved in the final report
- strict mode and quarantine mode work
- tests pass
- README matches the real behavior
