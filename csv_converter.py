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











def main():
    pass


if __name__ == "__main__":
    raise SystemExit(main())