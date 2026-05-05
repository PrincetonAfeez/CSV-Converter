"""Text artifact sanitizer for invisible and unsafe character-level content."""

# PINNED SNAPSHOT — sourced from https://github.com/PrincetonAfeez/String-Sanitizer
# This is the original copy of string_sanitizer.py pinned at the version that passed
# the DataGuard evaluation. Any updates must be replicated to all repositories within DataGuard.

# Enable postponed evaluation of type annotations for forward references
from __future__ import annotations

# Import the regular expression module for pattern matching
import re
# Import unicodedata to access the Unicode Character Database
import unicodedata
# Import the sys module for standard streams when run as a script
import sys


# Pre-compile a regex pattern to identify ANSI escape sequences (like terminal colors)
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)

# Define a mapping of non-standard Unicode whitespace characters to their descriptive names
UNICODE_WHITESPACE_MAP = {
    "\u00a0": "NO-BREAK SPACE",
    "\u1680": "OGHAM SPACE MARK",
    "\u2000": "EN QUAD",
    "\u2001": "EM QUAD",
    "\u2002": "EN SPACE",
    "\u2003": "EM SPACE",
    "\u2004": "THREE-PER-EM SPACE",
    "\u2005": "FOUR-PER-EM SPACE",
    "\u2006": "SIX-PER-EM SPACE",
    "\u2007": "FIGURE SPACE",
    "\u2008": "PUNCTUATION SPACE",
    "\u2009": "THIN SPACE",
    "\u200a": "HAIR SPACE",
    "\u202f": "NARROW NO-BREAK SPACE",
    "\u205f": "MEDIUM MATHEMATICAL SPACE",
    "\u3000": "IDEOGRAPHIC SPACE",
}

# Define a mapping to convert "smart" or curly quotes into standard ASCII straight quotes
SMART_QUOTES = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
}

# Identify invisible zero-width characters that can interfere with data processing
ZERO_WIDTH_CHARACTERS = {
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\u2060": "WORD JOINER",
    "\u00ad": "SOFT HYPHEN",
}

# Establish a consistent order for processing and reporting different artifact categories
CATEGORY_ORDER = [
    "bom_markers",
    "ansi_codes",
    "control_characters",
    "unicode_whitespace",
    "smart_quotes",
    "zero_width_characters",
]

# Default severity per category (findings may override, e.g. NUL bytes as high)
SEVERITY_BY_CATEGORY = {
    "bom_markers": "medium",
    "ansi_codes": "medium",
    "control_characters": "medium",
    "unicode_whitespace": "low",
    "smart_quotes": "low",
    "zero_width_characters": "medium",
}


# Create a list of dictionaries tracking each character and its original index in the text
def build_tracked_characters(text: str) -> list[dict]:
    return [{"char": character, "origin": index} for index, character in enumerate(text)]


# Calculate the human-readable line number for a specific character position in the string
def line_number_for_position(text: str, position: int) -> int:
    return text.count("\n", 0, max(position, 0)) + 1


# Return a string containing the hex codepoint and official Unicode name of a character
def describe_character(character: str) -> str:
    codepoint = f"U+{ord(character):04X}"
    name = unicodedata.name(character, "UNKNOWN")
    return f"{codepoint} {name}"


# Add a structured finding dictionary to the list of identified issues
def add_character_finding(
    findings: list[dict],
    category: str,
    text: str,
    position: int,
    message: str,
    *,
    severity: str | None = None,
) -> None:
    resolved_severity = severity if severity is not None else SEVERITY_BY_CATEGORY.get(category, "low")
    findings.append(
        {
            "severity": resolved_severity,
            "category": category,
            "line": line_number_for_position(text, position),
            "position": position,
            "message": message,
        }
    )


# Detect and remove the Byte Order Mark (BOM) if it exists at the start of the records
def strip_bom(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    if records and records[0]["char"] == "\ufeff":
        add_character_finding(
            findings,
            "bom_markers",
            original_text,
            records[0]["origin"],
            f"Removed BOM marker at position {records[0]['origin']}.",
        )
        return records[1:]
    return records


# Identify and strip ANSI escape codes using the pre-compiled regex pattern
def remove_ansi_codes(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    if not records:
        return records

    # Join characters back into a temporary string for regex scanning
    combined = "".join(record["char"] for record in records)
    kept_records = []
    current_index = 0

    # Iterate through all regex matches found in the combined string
    for match in ANSI_ESCAPE_PATTERN.finditer(combined):
        start, end = match.span()
        # Add the clean records that appeared before the current match
        kept_records.extend(records[current_index:start])
        # Record the original starting position of the ANSI sequence
        start_position = records[start]["origin"]
        # Escape the raw sequence for safe display in the findings report
        raw_sequence = match.group(0).encode("unicode_escape").decode("ascii")
        add_character_finding(
            findings,
            "ansi_codes",
            original_text,
            start_position,
            f"Removed ANSI escape sequence {raw_sequence} starting at position {start_position}.",
        )
        current_index = end

    # Append any remaining characters after the last match
    kept_records.extend(records[current_index:])
    return kept_records


# Remove non-printable control characters, excluding standard newlines and tabs
def strip_control_chars(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    kept_records = []
    for record in records:
        character = record["char"]
        # Check if ASCII value is in the control range (<32 or 127/DEL)
        if (ord(character) < 32 or ord(character) == 127) and character not in {"\n", "\t"}:
            control_severity = "high" if character == "\x00" else SEVERITY_BY_CATEGORY["control_characters"]
            add_character_finding(
                findings,
                "control_characters",
                original_text,
                record["origin"],
                f"Removed {describe_character(character)} at position {record['origin']}.",
                severity=control_severity,
            )
            continue
        kept_records.append(record)
    return kept_records


# Replace various Unicode space characters with a standard ASCII space
def normalize_whitespace(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    normalized = []
    for record in records:
        character = record["char"]
        if character in UNICODE_WHITESPACE_MAP:
            add_character_finding(
                findings,
                "unicode_whitespace",
                original_text,
                record["origin"],
                f"Normalized {describe_character(character)} to ASCII space at position {record['origin']}.",
            )
            # Add a new record representing the standardized space
            normalized.append({"char": " ", "origin": record["origin"]})
            continue
        normalized.append(record)
    return normalized


# Replace stylized/curly quotes with standard straight quotes
def normalize_smart_quotes(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    normalized = []
    for record in records:
        character = record["char"]
        if character in SMART_QUOTES:
            replacement = SMART_QUOTES[character]
            add_character_finding(
                findings,
                "smart_quotes",
                original_text,
                record["origin"],
                f"Normalized {describe_character(character)} to {replacement!r} at position {record['origin']}.",
            )
            # Substitute the character while keeping the original index tracking
            normalized.append({"char": replacement, "origin": record["origin"]})
            continue
        normalized.append(record)
    return normalized


# Remove invisible zero-width characters that can cause hidden data mismatches
def remove_zero_width(records: list[dict], original_text: str, findings: list[dict]) -> list[dict]:
    kept_records = []
    for record in records:
        character = record["char"]
        if character in ZERO_WIDTH_CHARACTERS:
            add_character_finding(
                findings,
                "zero_width_characters",
                original_text,
                record["origin"],
                f"Removed {describe_character(character)} at position {record['origin']}.",
            )
            continue
        kept_records.append(record)
    return kept_records


# Count the occurrences of each category of finding to generate a statistical summary
def summarize_findings(findings: list[dict]) -> dict:
    summary = {category: 0 for category in CATEGORY_ORDER}
    for finding in findings:
        summary[finding["category"]] = summary.get(finding["category"], 0) + 1
    severity_breakdown: dict[str, int] = {}
    for finding in findings:
        level = finding["severity"]
        severity_breakdown[level] = severity_breakdown.get(level, 0) + 1
    summary["severity_breakdown"] = severity_breakdown
    return summary


# Coordinate the full pipeline of text cleaning operations
def sanitize(text: str) -> tuple[str, list[dict], dict]:
    findings: list[dict] = []
    # Initialize the tracking list
    tracked = build_tracked_characters(text)
    # Execute sequential cleaning stages
    tracked = strip_bom(tracked, text, findings)
    tracked = remove_ansi_codes(tracked, text, findings)
    tracked = strip_control_chars(tracked, text, findings)
    tracked = normalize_whitespace(tracked, text, findings)
    tracked = normalize_smart_quotes(tracked, text, findings)
    tracked = remove_zero_width(tracked, text, findings)
    # Reassemble the cleaned characters into a final string
    cleaned = "".join(record["char"] for record in tracked)
    # Generate statistics for the operation
    stats = summarize_findings(findings)
    stats["original_characters"] = len(text)
    stats["cleaned_characters"] = len(cleaned)
    # Calculate the total delta between original and cleaned text
    stats["characters_removed_or_replaced"] = len(text) - len(cleaned) + stats["unicode_whitespace"] + stats["smart_quotes"]
    return cleaned, findings, stats


# Package the results into a standardized response dictionary
def build_result(cleaned_text: str, findings: list[dict], stats: dict, source_name: str = "<input>") -> dict:
    return {
        "module_name": "sanitize",
        "title": "DataGuard Sanitizer Report",
        "output": cleaned_text,
        "findings": findings,
        "warnings": [],
        "errors": [],
        "stats": stats,
        "metadata": {"source": source_name},
        "summary": (
            f"Removed or normalized {sum(stats.get(category, 0) for category in CATEGORY_ORDER)} "
            f"artifacts across {len(findings)} findings."
        ),
    }


# The primary entry point for executing the sanitizer on an input string
def run(input_text: str, config: dict | None = None) -> dict:
    # Ensure config is a dictionary even if None is provided
    config = config or {}
    # Run the sanitization logic
    cleaned_text, findings, stats = sanitize(input_text)
    # Return the formatted final report
    return build_result(cleaned_text, findings, stats, config.get("source_name", "<input>"))


# Command-line entry: read stdin as text, write sanitized text to stdout
def main() -> None:
    text = sys.stdin.read()
    cleaned, _, _ = sanitize(text)
    sys.stdout.write(cleaned)


if __name__ == "__main__":
    main()
