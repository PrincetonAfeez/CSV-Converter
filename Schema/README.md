# Schema Folder

This folder contains JSON Schema files for the `CSV-Converter` repository.

## Included schemas

### Shared
- `common.scalar.schema.json` — primitive cell values
- `common.finding.schema.json` — structured findings/diagnostics
- `common.string_list.schema.json` — warnings/errors arrays

### CSV converter
- `csv.config.schema.json` — input config for `csv_converter.run()`
- `csv.row.schema.json` — normalized row object
- `csv.quarantine_row.schema.json` — rejected raw row shape
- `csv.column_profile.schema.json` — inferred column profile
- `csv.stats.schema.json` — CSV report metrics
- `csv.metadata.schema.json` — CSV report metadata
- `csv.result.schema.json` — full report returned by `csv_converter.run()`
- `csv_converter_result.schema.json` — backward-compatible alias of `csv.result.schema.json`

### Sanitizer
- `sanitize.config.schema.json` — input config for `string_sanitizer.run()`
- `sanitize.stats.schema.json` — sanitizer counters and severity totals
- `sanitize.metadata.schema.json` — sanitizer metadata
- `sanitize.result.schema.json` — full report returned by `string_sanitizer.run()`

## Notes
- Schemas use JSON Schema Draft 2020-12.
- Relative `$ref` links assume the schemas stay in the same folder.
- The schemas model the current repo behavior and are suitable for validation, docs, and future refactors.
