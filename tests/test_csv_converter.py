"""Tests for csv_converter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import csv_converter


def test_detect_delimiter_counts_tie_prefers_comma() -> None:
    lines = ["a,b|c", "1,2|3"]
    best, _ = csv_converter.detect_delimiter(lines)
    assert best == ","


def test_looks_like_header_accepts_duplicate_column_names() -> None:
    assert csv_converter.looks_like_header(["Name", "Name", "Age"])


def test_clean_cell_null_placeholder() -> None:
    assert csv_converter.clean_cell("  N/A  ") is None


def test_run_simple_csv() -> None:
    text = "a,b\n1,2\n3,4\n"
    result = csv_converter.run(text, {"source_name": "t.csv"})
    rows = json.loads(result["output"])
    assert rows == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert result["stats"]["rows_converted"] == 2
    assert result["stats"]["rows_attempted"] == 2
    assert result["stats"]["row_acceptance_rate_pct"] == 100.0


def test_run_strict_rejects_short_row() -> None:
    text = "a,b,c\n1,2\n"
    result = csv_converter.run(text, {"strict": True})
    assert result["stats"]["rows_rejected"] == 1
    assert result["stats"]["rows_converted"] == 0
    assert result["quarantine_rows"]


def test_run_no_types() -> None:
    text = "x\n42\n"
    result = csv_converter.run(text, {"no_types": True})
    row = json.loads(result["output"])[0]
    assert row["x"] == "42"


def test_cli_writes_json(tmp_path: Path) -> None:
    inp = tmp_path / "in.csv"
    outp = tmp_path / "out.json"
    inp.write_text("u,v\na,b\n", encoding="utf-8")
    script = Path(csv_converter.__file__).resolve()
    proc = subprocess.run(
        [sys.executable, str(script), "--file", str(inp), "--output", str(outp)],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data == [{"u": "a", "v": "b"}]


def test_cli_missing_file_exit_code(tmp_path: Path) -> None:
    script = Path(csv_converter.__file__).resolve()
    missing = tmp_path / "nope.csv"
    proc = subprocess.run(
        [sys.executable, str(script), "--file", str(missing)],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "Could not read" in proc.stderr
