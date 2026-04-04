App: CLI CSV-to-JSON Converter & Repairer

What it does: Ingests a CSV file and diagnoses its problems: missing headers, inconsistent column counts, empty cells, mixed delimiters (commas vs. semicolons vs. tabs), encoding issues, quoted fields with embedded newlines. Repairs what it can (with warnings), rejects what it can't (with explanations), and outputs a clean JSON file.

Why it matters: CSV is the most common data exchange format and the most consistently broken. Handling every edge case is a masterclass in defensive programming.

Key skills: RegEx for delimiter detection, encoding detection, the CSV module's edge cases, JSON serialization with type inference (string vs. number vs. boolean vs. null), and validation reporting.

Standalone value: Fix any broken CSV and convert it to clean JSON.

Mega-app role: dataguard/csv_doctor.py — handles tabular data in the pipeline.

Features:
CLI Interface
•	--file flag (required) pointing to the input CSV
•	--output flag for JSON destination (defaults to output.json)
•	--delimiter flag to force a delimiter or auto-detect (default: auto)
•	--strict flag to reject all rows with any issue instead of repairing them
•	--quarantine flag to write rejected rows to a separate CSV file for review
•	--no-types flag to skip data type inference and treat all values as strings
•	--report flag to print the full diagnostic report to terminal

Delimiter Detection
•	Auto-detection by counting commas, semicolons, tabs, and pipes across the first 10 lines
•	Confidence label: high if one delimiter dominates, low if counts are close
•	Mixed delimiter warnings per line: Line 47 uses semicolons but the rest uses commas
•	Manual override via --delimiter flag

Header Diagnosis & Repair
•	Detects if the first row is a header by checking: all-string values, no duplicates, not purely numeric
•	Missing headers auto-generated as column_1, column_2, etc. with a warning
•	Duplicate headers get _2, _3 suffixes; empty headers become unnamed_column_N
•	Whitespace in headers trimmed with a notice

Column Count Consistency
•	Expected column count established from the header row
•	Too few columns: padded with null values at the end, with a warning per row
•	Too many columns: extra values moved to an _overflow field, or truncated with a warning
•	Data quality percentage reported: consistent rows vs. inconsistent rows

Empty Cell Handling
•	Detects truly empty cells, whitespace-only cells, and placeholders: N/A, null, NULL, -, --, none
•	All normalized to JSON null
•	Per-column completeness score: percentage of non-null values

Encoding Detection & Repair
•	UTF-8 BOM detection and stripping
•	Common mojibake pattern flagging (e.g., Ã© suggesting UTF-8 read as Latin-1)
•	Control character stripping (0x00–0x1F except newline/tab) with a warning per occurrence

Data Type Inference
•	Per-column type sniffing: string, integer, float, boolean, or empty
•	Type mismatch flagging: if a column is 90%+ numeric but has string outliers, those cells are flagged
•	Boolean normalization: yes/no, true/false, 1/0, Y/N all converted to JSON true/false
•	Numeric cleanup: strips currency symbols, thousand separators, trailing percent signs

Repair vs. Rejection Logic
•	Repairable issues fixed automatically with a yellow warning: padding, normalization, trimming, duplicate headers
•	Rejected rows excluded from JSON with a red error and explanation: unparseable lines, rows below 50% expected columns, binary garbage
•	Quarantine list optionally written to a separate file via --quarantine
•	Final tally: N rows converted, N repaired, N rejected

JSON Output
•	Clean JSON array of objects, keys from header names, proper escaping
•	Pretty-printed with 2-space indentation

Diagnostic Report
•	File overview: total lines, delimiter, encoding, header status, column count
•	Data quality scorecard: parse rate, column consistency, cell completeness, type consistency
•	Per-column profile: name, inferred type, completeness, mismatches, repairs
•	All printed to terminal as a structured section-by-section report

Student-Level Code Style
•	A character-by-character parser with state variables: inside_quotes, current_cell, current_row with comments at each transition
•	Functions: detect_delimiter(), check_headers(), validate_column_counts(), infer_types()
•	Names like lines_with_wrong_column_count and rows_sent_to_quarantine
•	Uses only: re, csv, json, argparse, os, sys, collections
•	Comments like # semicolons are common in European CSVs where commas are decimal separators

This is a structural repair tool designed to handle "malformed" tabular data. It goes far beyond a simple format change by applying defensive programming to fix common data entry errors.
•	Automated Structural Discovery: It uses statistical analysis to "guess" the delimiter (comma, semicolon, pipe, or tab) with a calculated confidence score.
•	Header Intelligence: It differentiates between data and headers using heuristics (checking for numeric density and uniqueness) and automatically repairs missing, empty, or duplicate column names.
•	Row-Level Surgery: It detects "short" rows (missing columns) and "long" rows (extra columns). It pads short rows with nulls and moves extra data into a special _overflow field rather than deleting it.
•	Schema Inference: The module scans every value in a column to determine the most likely data type (Integer, Float, Boolean, or String) and attempts to cast the data into those types for the final JSON output.
•	Data Quality Profiling: It generates a "Completeness" metric for every column, telling the user exactly what percentage of their data is populated vs. null.

The Tech Stack
Technology	Role in the Project
Python 3.10+	Utilizes defaultdict and Counter for high-performance data grouping and frequency analysis.
csv Module	The fundamental parser used to handle RFC 4180 compliance and complex quoting scenarios.
json Module	Used to serialize the repaired Python dictionaries into a web-ready, structured string.
Regex (re)	Employed for "Type Discovery"—identifying patterns like currency, percentages, and numeric strings.
io.StringIO	Enables "virtual file" processing, allowing the script to treat raw text strings as file streams for the CSV reader.

1. Statistical Delimiter Detection
By using collections.Counter to weigh delimiter candidates across the first several lines, the tool avoids the "Global Fail" common in static parsers. If a file uses ; instead of ,, the script adapts dynamically, making it much more resilient to varied regional data formats.

2. Non-Destructive Overflow Handling
Unlike standard CSV-to-JSON converters that crash or truncate data when a row has "too many" columns, this stack uses a "Quarantine & Overflow" logic. By saving extra data in an _overflow key, the tech stack ensures that zero data loss occurs during the conversion process.



3. In-Memory "Virtual" Streams
The use of io.StringIO is a professional-grade choice for performance. It allows the script to leverage the speed of the C-based csv module without the overhead of writing temporary files to the hard drive, which is critical for processing large datasets quickly.

4. Semantic Data Typing
By combining re with a column-wide scan, the tech stack transforms "flat" text into "rich" data. Converting "true" into a Boolean True or "$1,200.50" into a Float 1200.5 significantly reduces the amount of work required for the next developer or system using this data.

