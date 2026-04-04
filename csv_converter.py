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

def detect_delimiter(lines: list[str]) -> tuple[str, str]:
    candidates = [",", ";", "\t", "|"]
    counts = {}
    for delimiter in candidates:
        counts[delimiter] = sum(line.count(delimiter) for line in lines[:10] if line.strip())
    tie_break_order = [",", ";", "\t", "|"]
    max_count = max(counts.values()) if counts else 0
    tied = [d for d in tie_break_order if counts.get(d, 0) == max_count]
    best = tied[0] if tied else ","
    sorted_counts = sorted(counts.values(), reverse=True)
    confidence = "high" if len(sorted_counts) < 2 or sorted_counts[0] >= sorted_counts[1] * 1.5 else "low"
    return best, confidence

def looks_like_header(row: list[str]) -> bool:
    if not row:
        return False
    cleaned = [cell.strip() for cell in row]
    if all(re.fullmatch(r"-?\d+(?:\.\d+)?", cell or "") for cell in cleaned if cell):
        return False
    return any(cell for cell in cleaned)

def normalize_headers(header_row: list[str]) -> tuple[list[str], list[dict]]:
    findings = []
    normalized = []
    seen = Counter()

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
        elif header != raw_header:
            findings.append(
                {
                    "severity": "low",
                    "category": "header_trim",
                    "line": 1,
                    "message": f"Trimmed whitespace in header {raw_header!r}.",
                }
            )

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

def parse_csv_rows(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [row for row in reader]

def clean_cell(value: str) -> str | None:
    trimmed = value.strip()
    if trimmed.lower() in EMPTY_CELL_VALUES:
        return None
    return trimmed

def detect_type(values: list[str | None]) -> str:
    non_empty = [value for value in values if value not in {None, ""}]
    if not non_empty:
        return "empty"
    if all(str(value).lower() in {"true", "false", "yes", "no", "1", "0", "y", "n"} for value in non_empty):
        return "boolean"
    if all(re.fullmatch(r"-?\d+", str(value)) for value in non_empty):
        return "integer"
    if all(re.fullmatch(r"-?\d+(?:\.\d+)?%?", str(value).replace(",", "").replace("$", "")) for value in non_empty):
        return "float"
    return "string"

def convert_value(value: str | None, target_type: str):
    if value is None:
        return None
    if target_type == "boolean":
        return str(value).lower() in {"true", "yes", "1", "y"}
    if target_type == "integer":
        return int(str(value).replace(",", "").replace("$", ""))
    if target_type == "float":
        cleaned = str(value).replace(",", "").replace("$", "").rstrip("%")
        return float(cleaned)
    return value

def run(input_text: str, config: dict | None = None) -> dict:
    config = config or {}
    sanitized = string_sanitizer.run(input_text, {"source_name": config.get("source_name", "<input>")})
    cleaned_text = sanitized["output"]
    lines = cleaned_text.splitlines()
    findings = list(sanitized["findings"])
    
    delimiter_flag = config.get("delimiter", "auto")
    if delimiter_flag == "auto":
        delimiter, confidence = detect_delimiter(lines)
    else:
        delimiter = DELIMITER_LABELS.get(delimiter_flag, delimiter_flag)
        confidence = "manual"

    raw_rows = parse_csv_rows(cleaned_text, delimiter)

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
    mixed_delimiter_lines = []
    for line_number, line in enumerate(lines[:100], start=1):
        if not line.strip():
            continue
        other_counts = {candidate: line.count(candidate) for candidate in [",", ";", "\t", "|"] if candidate != delimiter}
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



















def main():
    pass


if __name__ == "__main__":
    raise SystemExit(main())