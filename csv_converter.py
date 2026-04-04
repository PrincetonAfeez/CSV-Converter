"""CSV repair and JSON conversion."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import string_sanitizer


DELIMITER_LABELS = {"auto": None, ",": ",", ";": ";", "|": "|", "tab": "\t"}
EMPTY_CELL_VALUES = {"", "n/a", "null", "-", "--", "none", "na"}


# Analyze the first few lines of text to guess which character is used as a delimiter
def detect_delimiter(lines: list[str]) -> tuple[str, str]:
    # List of common characters used to separate values in text files
    candidates = [",", ";", "\t", "|"]
    counts = {}
    # Count occurrences of each candidate in the first 10 non-empty lines
    for delimiter in candidates:
        counts[delimiter] = sum(line.count(delimiter) for line in lines[:10] if line.strip())
    # Highest count wins; on ties prefer comma, then semicolon, tab, pipe (stable regional default).
    tie_break_order = [",", ";", "\t", "|"]
    max_count = max(counts.values()) if counts else 0
    tied = [d for d in tie_break_order if counts.get(d, 0) == max_count]
    best = tied[0] if tied else ","
    # Sort counts to determine if the "winner" won by a significant margin
    sorted_counts = sorted(counts.values(), reverse=True)
    # Assign high confidence if the top choice is at least 1.5x more frequent than the runner-up
    confidence = "high" if len(sorted_counts) < 2 or sorted_counts[0] >= sorted_counts[1] * 1.5 else "low"
    return best, confidence


# Use heuristics to determine if the first row is a header or just more data
def looks_like_header(row: list[str]) -> bool:
    # If the row is empty, it's definitely not a header
    if not row:
        return False
    # Clean whitespace from each cell for accurate checking
    cleaned = [cell.strip() for cell in row]
    # If every cell looks like a number, it's likely a data row, not a header
    if all(re.fullmatch(r"-?\d+(?:\.\d+)?", cell or "") for cell in cleaned if cell):
        return False
    # Duplicate labels still count as headers; normalize_headers() de-duplicates them.
    return any(cell for cell in cleaned)


# Standardize header names by trimming whitespace, filling blanks, and de-duplicating
def normalize_headers(header_row: list[str]) -> tuple[list[str], list[dict]]:
    findings = []
    normalized = []
    seen = Counter()

    # Iterate through each raw header string provided in the first row
    for index, raw_header in enumerate(header_row, start=1):
        header = raw_header.strip()
        # If a header is missing, generate a placeholder name and log a finding
        if not header:
            header = f"unnamed_column_{index}"
            findings.append(
                {
                    "severity": "low",
                    "category": "header_repair",
                    "line": 1,
                    "message": f"Header {index} was empty and became {header}.",
                }
            )
        # Log a finding if we had to trim surrounding whitespace
        elif header != raw_header:
            findings.append(
                {
                    "severity": "low",
                    "category": "header_trim",
                    "line": 1,
                    "message": f"Trimmed whitespace in header {raw_header!r}.",
                }
            )

        # Track name occurrences to handle duplicates (e.g., 'ID' and 'ID' becomes 'ID' and 'ID_2')
        seen[header] += 1
        if seen[header] > 1:
            new_header = f"{header}_{seen[header]}"
            findings.append(
                {
                    "severity": "low",
                    "category": "duplicate_header",
                    "line": 1,
                    "message": f"Duplicate header {header!r} renamed to {new_header}.",
                }
            )
            header = new_header

        normalized.append(header)

    return normalized, findings


# Use Python's native CSV engine to split the text into a list of lists
def parse_csv_rows(text: str, delimiter: str) -> list[list[str]]:
    # Use io.StringIO to treat the string as a file object
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [row for row in reader]


# Standardize cell content by trimming and converting "null-like" strings to None
def clean_cell(value: str) -> str | None:
    trimmed = value.strip()
    if trimmed.lower() in EMPTY_CELL_VALUES:
        return None
    return trimmed


# Inspect a list of values in a column to guess the most likely data type
def detect_type(values: list[str | None]) -> str:
    # Filter out empty cells to focus on actual data
    non_empty = [value for value in values if value not in {None, ""}]
    if not non_empty:
        return "empty"
    # Check if all values represent boolean states
    if all(str(value).lower() in {"true", "false", "yes", "no", "1", "0", "y", "n"} for value in non_empty):
        return "boolean"
    # Check if all values are whole numbers
    if all(re.fullmatch(r"-?\d+", str(value)) for value in non_empty):
        return "integer"
    # Check if all values are decimal numbers, potentially including % or $ symbols
    if all(re.fullmatch(r"-?\d+(?:\.\d+)?%?", str(value).replace(",", "").replace("$", "")) for value in non_empty):
        return "float"
    # Default to string if no other type fits perfectly
    return "string"


# Cast a string value into its inferred Python type (int, float, bool)
def convert_value(value: str | None, target_type: str):
    if value is None:
        return None
    if target_type == "boolean":
        return str(value).lower() in {"true", "yes", "1", "y"}
    if target_type == "integer":
        # Clean formatting characters before converting to integer
        return int(str(value).replace(",", "").replace("$", ""))
    if target_type == "float":
        # Clean formatting characters and percent signs before converting to float
        cleaned = str(value).replace(",", "").replace("$", "").rstrip("%")
        return float(cleaned)
    return value


# Main conversion logic for the CSV module
def run(input_text: str, config: dict | None = None) -> dict:
    config = config or {}
    # Pre-clean the input using the sanitizer
    sanitized = string_sanitizer.run(input_text, {"source_name": config.get("source_name", "<input>")})
    cleaned_text = sanitized["output"]
    lines = cleaned_text.splitlines()
    findings = list(sanitized["findings"])

    # Determine delimiter: either auto-detect or use the user-defined one
    delimiter_flag = config.get("delimiter", "auto")
    if delimiter_flag == "auto":
        delimiter, confidence = detect_delimiter(lines)
    else:
        delimiter = DELIMITER_LABELS.get(delimiter_flag, delimiter_flag)
        confidence = "manual"

    # Parse text into raw rows
    raw_rows = parse_csv_rows(cleaned_text, delimiter)
    # Handle empty input gracefully
    if not raw_rows:
        return {
            "module_name": "csv",
            "title": "DataGuard CSV Doctor Report",
            "output": "[]",
            "rows": [],
            "quarantine_rows": [],
            "findings": findings,
            "warnings": ["CSV input was empty."],
            "errors": [],
            "stats": {
                "rows_converted": 0,
                "rows_repaired": 0,
                "rows_rejected": 0,
                "rows_attempted": 0,
                "row_acceptance_rate_pct": 0.0,
                "delimiter": repr(delimiter),
                "delimiter_confidence": confidence,
                "header_status": "none",
                "expected_columns": 0,
                "mixed_delimiter_lines": 0,
                "type_mismatches": 0,
            },
            "metadata": {
                "source": config.get("source_name", "<input>"),
                "delimiter": repr(delimiter),
                "delimiter_char": delimiter,
            },
            "column_profiles": [],
            "summary": "No rows were converted because the input was empty.",
        }

    # Check for "delimiter drift" where lines might use a different separator than the rest
    mixed_delimiter_lines = []
    for line_number, line in enumerate(lines[:100], start=1):
        if not line.strip():
            continue
        # Count other potential delimiters
        other_counts = {candidate: line.count(candidate) for candidate in [",", ";", "\t", "|"] if candidate != delimiter}
        # If another candidate is more common on this specific line, log it as a risk
        if any(count > line.count(delimiter) and count > 0 for count in other_counts.values()):
            mixed_delimiter_lines.append(line_number)
            findings.append(
                {
                    "severity": "low",
                    "category": "mixed_delimiter",
                    "line": line_number,
                    "message": f"Line {line_number} appears to mix delimiters while {repr(delimiter)} is primary.",
                }
            )

    # Process headers: either normalize the first row or generate generic headers
    first_row = raw_rows[0]
    if looks_like_header(first_row):
        headers, header_findings = normalize_headers(first_row)
        data_rows = raw_rows[1:]
        header_status = "provided"
    else:
        headers = [f"column_{index}" for index in range(1, len(first_row) + 1)]
        header_findings = [
            {
                "severity": "medium",
                "category": "missing_header",
                "line": 1,
                "message": "First row did not look like a header, so column_1 style headers were generated.",
            }
        ]
        data_rows = raw_rows
        header_status = "generated"
    findings.extend(header_findings)

    # Initialize row-level processing variables
    expected_columns = len(headers)
    strict_mode = bool(config.get("strict"))
    no_types = bool(config.get("no_types"))
    repaired_rows = 0
    rejected_rows = 0
    quarantine_rows = []
    converted_rows = []

    # Loop through data rows and repair structural mismatches
    for row_index, raw_row in enumerate(data_rows, start=2 if header_status == "provided" else 1):
        row = list(raw_row)
        # Reject rows that are extremely short (less than half the expected length)
        if len(row) < max(1, expected_columns // 2):
            rejected_rows += 1
            findings.append(
                {
                    "severity": "medium",
                    "category": "rejected_row",
                    "line": row_index,
                    "message": f"Row had only {len(row)} columns versus expected {expected_columns}.",
                }
            )
            quarantine_rows.append(raw_row)
            continue

        row_dict = {}
        overflow_values = None

        # Handle rows that are shorter than the header row
        if len(row) < expected_columns:
            if strict_mode:
                rejected_rows += 1
                quarantine_rows.append(raw_row)
                findings.append(
                    {
                        "severity": "medium",
                        "category": "strict_rejection",
                        "line": row_index,
                        "message": f"Strict mode rejected short row with {len(row)} columns.",
                    }
                )
                continue
            # Pad the row with empty strings to match the header length
            row.extend([""] * (expected_columns - len(row)))
            repaired_rows += 1
            findings.append(
                {
                    "severity": "low",
                    "category": "row_padding",
                    "line": row_index,
                    "message": f"Padded short row from {len(raw_row)} to {expected_columns} columns.",
                }
            )
        # Handle rows that have more columns than the header row
        elif len(row) > expected_columns:
            overflow_values = row[expected_columns:]
            if strict_mode:
                rejected_rows += 1
                quarantine_rows.append(raw_row)
                findings.append(
                    {
                        "severity": "medium",
                        "category": "strict_rejection",
                        "line": row_index,
                        "message": f"Strict mode rejected long row with {len(row)} columns.",
                    }
                )
                continue
            # Truncate the row and save the extra data in a special overflow field
            row = row[:expected_columns]
            repaired_rows += 1
            findings.append(
                {
                    "severity": "low",
                    "category": "row_overflow",
                    "line": row_index,
                    "message": "Moved extra columns into _overflow.",
                }
            )

        # Map row values to their respective headers
        for header, value in zip(headers, row):
            row_dict[header] = clean_cell(value)
        # Include overflow data if it exists
        if overflow_values:
            row_dict["_overflow"] = [clean_cell(value) for value in overflow_values]

        converted_rows.append(row_dict)

    # Group all values by column to perform type inference (always include every header)
    column_values: dict[str, list] = {header: [] for header in headers}
    for row in converted_rows:
        for header in headers:
            column_values[header].append(row.get(header))

    # Detect the most likely type for every column
    inferred_types = {header: detect_type(values) for header, values in column_values.items()}
    type_mismatches = 0
    # Apply type conversion unless disabled by user
    if not no_types:
        for row_index, row in enumerate(converted_rows, start=1):
            for header, target_type in inferred_types.items():
                value = row.get(header)
                if value is None or target_type in {"string", "empty"}:
                    continue
                try:
                    row[header] = convert_value(value, target_type)
                except ValueError:
                    type_mismatches += 1
                    findings.append(
                        {
                            "severity": "low",
                            "category": "type_mismatch",
                            "line": row_index,
                            "message": f"Value {value!r} in column {header} did not fit inferred type {target_type}.",
                        }
                    )

    # Calculate the percentage of non-null values per column
    completeness = {}
    for header, values in column_values.items():
        non_null = sum(1 for value in values if value is not None)
        completeness[header] = round((non_null / max(len(values), 1)) * 100, 1)

    # Generate final JSON string output
    output_json = json.dumps(converted_rows, indent=2, ensure_ascii=False)
    rows_attempted = len(converted_rows) + rejected_rows
    if rows_attempted:
        acceptance_pct = round((len(converted_rows) / rows_attempted) * 100, 1)
    else:
        acceptance_pct = 100.0
    stats = {
        "rows_converted": len(converted_rows),
        "rows_repaired": repaired_rows,
        "rows_rejected": rejected_rows,
        "rows_attempted": rows_attempted,
        "row_acceptance_rate_pct": acceptance_pct,
        "delimiter": repr(delimiter),
        "delimiter_confidence": confidence,
        "header_status": header_status,
        "expected_columns": expected_columns,
        "mixed_delimiter_lines": len(mixed_delimiter_lines),
        "type_mismatches": type_mismatches,
    }

    # Prepare report metadata
    metadata = {
        "source": config.get("source_name", "<input>"),
        "delimiter": repr(delimiter),
        "delimiter_char": delimiter,
        "header_status": header_status,
    }

    if confidence == "manual":
        delim_part = f"Delimiter {repr(delimiter)} (manual override)."
    else:
        delim_part = f"Delimiter {repr(delimiter)} with {confidence} confidence."
    if rows_attempted:
        rate_part = f" Row acceptance {acceptance_pct}% ({len(converted_rows)}/{rows_attempted} data rows)."
    else:
        rate_part = " No data rows after the header."
    summary = (
        f"Converted {len(converted_rows)} rows to JSON, repaired {repaired_rows}, rejected {rejected_rows}. "
        f"{delim_part}{rate_part}"
    )

    # Return the full multi-part result dictionary
    return {
        "module_name": "csv",
        "title": "DataGuard CSV Doctor Report",
        "output": output_json,
        "rows": converted_rows,
        "quarantine_rows": quarantine_rows,
        "findings": findings,
        "warnings": [f"{rejected_rows} rows were rejected."] if rejected_rows else [],
        "errors": [],
        "stats": stats,
        "metadata": metadata,
        "column_profiles": [{"name": header, "type": inferred_types[header], "completeness": completeness[header]} for header in headers],
        "summary": summary,
    }

# Write quarantined rows to a CSV file using the same delimiter as the main output
def write_quarantine_csv(path: Path, rows: list[list[str]], delimiter: str) -> None:
    if not rows:
        return
    width = max(len(r) for r in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        for row in rows:
            writer.writerow(list(row) + [""] * (width - len(row)))

# Nicely format the report for human reading in the command-line interface
def print_report(result: dict) -> None:
    title = result.get("title", "Report")
    print(title)
    print("=" * len(title))
    print(result.get("summary", ""))
    print()
    print("Stats")
    print("-----")
    print(json.dumps(result.get("stats", {}), indent=2, ensure_ascii=False))
    print()
    print("Metadata")
    print("--------")
    print(json.dumps(result.get("metadata", {}), indent=2, ensure_ascii=False))
    print()
    profiles = result.get("column_profiles") or []
    if profiles:
        print("Column profiles")
        print("---------------")
        print(json.dumps(profiles, indent=2, ensure_ascii=False))
        print()
    warnings = result.get("warnings") or []
    if warnings:
        print("Warnings")
        print("--------")
        for w in warnings:
            print(f"  - {w}")
        print()
    findings = result.get("findings") or []
    print(f"Findings ({len(findings)})")
    print("---------")
    for item in findings[:200]:
        print(f"  [{item.get('severity', '?')}] {item.get('message', '')}")
    if len(findings) > 200:
        print(f"  ... and {len(findings) - 200} more")

# Main entry point for command-line execution
def main(argv: list[str] | None = None) -> int:
    from errors import InputError
# Set up command-line argument parsing for the CSV repair tool
    parser = argparse.ArgumentParser(description="Repair CSV and convert to JSON with diagnostics.")
    parser.add_argument("--file", "-f", required=True, help="Input CSV file path")
    parser.add_argument("--output", "-o", default="output.json", help="Output JSON path (default: output.json)")
    parser.add_argument(
        "--delimiter",
        "-d",
        default="auto",
        choices=["auto", ",", ";", "|", "tab"],
        help="Field delimiter or auto-detect (default: auto)",
    )
    parser.add_argument("--strict", action="store_true", help="Reject rows with wrong column count instead of repairing")
    parser.add_argument("--quarantine", metavar="PATH", help="Write rejected rows to this CSV file")
    parser.add_argument("--no-types", action="store_true", dest="no_types", help="Skip type inference; keep string values")
    parser.add_argument("--report", action="store_true", help="Print full diagnostic report to stdout")
    ns = parser.parse_args(argv)

    path = Path(ns.file)
    try:
        input_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(InputError(f"Could not read {path}: {exc}"), file=sys.stderr)
        return 1

    result = run(
        input_text,
        {
            "source_name": str(path.resolve()),
            "delimiter": ns.delimiter,
            "strict": ns.strict,
            "no_types": ns.no_types,
        },
    )

# Write the main output JSON to the specified file
    out_path = Path(ns.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result["output"], encoding="utf-8")

# If any rows were quarantined, write them to the specified CSV file with the same delimiter
    if ns.quarantine:
        qpath = Path(ns.quarantine)
        delim = result.get("metadata", {}).get("delimiter_char", ",")
        write_quarantine_csv(qpath, result.get("quarantine_rows") or [], delim)

    if ns.report:
        print_report(result)

    return 0

# Allow the module to be run as a script
if __name__ == "__main__":
    raise SystemExit(main())