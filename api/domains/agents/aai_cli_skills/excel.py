"""aai-cli excel skill docs.

Unlike every other aai-cli skill this one requires no provider credential — it works on
local spreadsheet files — so it is seeded with an empty ``required_providers`` list and is
mounted only when explicitly assigned to an agent.
"""

EXCEL_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/excel_skill.md",
        "skill_content": r"""\
# aai-cli Excel Skill

Agent reference for the `aai-cli excel` command group.

## IMPORTANT: no credentials, no profile

Excel commands read and write local spreadsheet files. There is no account or integration
behind them. **Do not pass `--profile`**, and never ask the user to authenticate or supply
credentials for Excel work.

```
aai-cli excel <resource> <action> <FILE> [args]
```

`FILE` is a path to a spreadsheet file. Use `workbook create` to make a new one; every
other command edits an existing file in place.

## Supported formats

| Extension | Read | Write | Notes |
|---|---|---|---|
| `.xlsx`, `.xlsm` | yes | yes | Macros in `.xlsm` are preserved. |
| `.csv` | yes | yes | Comma-delimited. One sheet, named after the file stem. |
| `.tsv`, `.tab` | yes | yes | Tab-delimited. Otherwise identical to `.csv`. |
| `.xls`, `.xla` | yes | **no** | Legacy Excel 97–2003 (BIFF). |
| `.xlsb` | yes | **no** | Binary workbook. |
| `.ods` | yes | **no** | OpenDocument. |

Read-only responses carry `"readOnly": true`. Writing to one fails with `invalid_input`
telling you to save as `.xlsx` or `.csv` first; `--force` does not override it.

Format is chosen by extension. A file whose contents do not match its extension is
diagnosed specifically — an HTML table named `.xls` (common from legacy "export to Excel"
buttons), delimited text named `.xls`, or a zip workbook named `.xls` each get their own
message saying what to rename it to.

### Delimited-file behaviour

- The single sheet takes the file's stem as its name (`sales.csv` → `'sales'!A1:C3`).
  Naming any other sheet is an error.
- `--sheets` is rejected by `workbook create` for these files — there is only one sheet.
- Types are inferred on read, but **only when the parsed value renders back to exactly the
  original text**. `20.5` and `true` come back as a number and a boolean; `007`, `1.50`,
  `+3` and ` 42` stay strings so identifiers and padding are never silently rewritten.
- Quoting follows RFC 4180 — embedded commas, quotes and newlines survive a round trip.

### Editing an .xlsx rewrites the whole workbook

Charts, pivot tables, form controls, external links, custom XML and sensitivity labels
cannot survive that rewrite. Rather than lose them silently, a write to such a workbook is
**refused** with a message naming what would be dropped:

```
refusing to write report.xlsx: saving rewrites the whole workbook and would drop
1 chart, 1 pivot table. Pass --force to write anyway, or copy the values into a new
file instead.
```

Tell the user what would be lost and let them decide; only pass `--force` when they have
accepted it. Cell values, formatting and `.xlsm` macros are preserved, so plain data
workbooks are never blocked.

## Ranges

A1 notation, the same forms the `sheets` command accepts:

| Form | Meaning |
|---|---|
| `'Sheet1'!A1:D5` | An explicit rectangle on a named tab |
| `A1:D5` | The same rectangle on the first tab |
| `C7` | A single cell |
| `'Sheet1'!B:C` | Columns B–C, down to the last used row |
| `'Sheet1'!2:5` | Rows 2–5, across to the last used column |
| `Sheet1` | Everything in use on that tab |

Quote a tab name if it contains spaces or punctuation, and double any apostrophe inside it
(`'It''s Data'!A1`). A bare name that is also a valid cell reference — `Sheet1` — is read as
the tab when the workbook has one by that name.

## Response shapes

**`sheets list`** returns a `sheets` array. Each element has `index`, `title`, `usedRange`, `rowCount`, and `columnCount`.

**`values get`** returns a `values` array of arrays, one inner array per row. Types are preserved from the workbook: numbers come back as numbers (`20.5`) and booleans as `true`/`false`. Trailing empty cells and rows are omitted rather than padded.

**`values update`** returns `updatedRange`, `updatedRows`, `updatedColumns`, `updatedCells`.

**`values clear`** returns `clearedRange` and `clearedCells`.

**`sheets add` / `sheets delete` / `sheets rename`** return the affected title (`added`, `deleted`, or `renamed` plus `to`) and the workbook's full `sheets` title list afterwards.

Every response echoes the `file` it acted on, plus `truncated: false` — these commands
always return the whole answer, so there is never a further page to fetch. The
`range`/`updatedRange`/`clearedRange` strings are valid input for a follow-up command.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "not_found",
  "details": null,
  "message": "no sheet named \"Nope\"; workbook has: Sheet1, Summary",
  "operation": "values.get",
  "service": "excel",
  "status": null
}
```

| Code | Meaning |
|---|---|
| `not_found` | The file or the named sheet doesn't exist |
| `invalid_input` | The range or `--values` payload was malformed, the file isn't readable in its format, the write was refused to protect workbook features, or the file is a read-only format |
| `internal_error` | The workbook could not be written back |

Exit code is non-zero on any error.

---

## workbook create

Create a new, empty file.

```
aai-cli excel workbook create <FILE> [--sheets "Name1,Name2"] [--force]
```

| Argument/Flag | Required | Description |
|---|---|---|
| `FILE` | **yes** | Path to write the new file to (.xlsx or .csv/.tsv) |
| `--sheets` | no | Comma-separated tab names (.xlsx only). Defaults to a single `Sheet1` |
| `--force` | no | Overwrite the file if it already exists |

Refuses to clobber an existing file unless `--force` is passed. Tab names must be unique.

**Example**

```
aai-cli excel workbook create ./report.xlsx --sheets "Summary,Q1 Data"
```

```json
{
  "file": "./report.xlsx",
  "created": true,
  "sheets": ["Summary", "Q1 Data"]
}
```

Follow it with `values update` to fill the new tabs.

---

## sheets list

List every tab in the workbook, with the extent of its data.

```
aai-cli excel sheets list <FILE>
```

**Example**

```
aai-cli excel sheets list ./inventory.xlsx
```

```json
{
  "file": "./inventory.xlsx",
  "sheets": [
    {
      "index": 0,
      "title": "Sheet1",
      "usedRange": "'Sheet1'!A1:C3",
      "rowCount": 3,
      "columnCount": 3
    }
  ]
}
```

Use `title` to build range strings, and `usedRange` to see how much data a tab holds
before reading it.

---

## sheets add

Add a new empty tab to the end of an `.xlsx` workbook.

```
aai-cli excel sheets add <FILE> <TITLE> [--force]
```

| Argument/Flag | Required | Description |
|---|---|---|
| `FILE` | **yes** | Path to the `.xlsx` workbook |
| `TITLE` | **yes** | Title for the new tab. Must not already exist |
| `--force` | no | Write even when the workbook holds features a rewrite would drop |

Tab names follow Excel's rules: at most 31 characters, and never `: \ / ? * [ ]`.

**Example**

```
aai-cli excel sheets add ./inventory.xlsx "Q4"
```

```json
{
  "file": "./inventory.xlsx",
  "added": "Q4",
  "sheets": ["Sheet1", "Q4"],
  "truncated": false
}
```

---

## sheets delete

Delete a tab from an `.xlsx` workbook. This destroys that tab's data — confirm with the
user first.

```
aai-cli excel sheets delete <FILE> <TITLE> [--force]
```

Refused when the tab is the workbook's last one (a workbook must keep at least one), or
when a formula elsewhere still references it.

---

## sheets rename

Rename a tab in an `.xlsx` workbook.

```
aai-cli excel sheets rename <FILE> <TITLE> <NEW_TITLE> [--force]
```

| Argument/Flag | Required | Description |
|---|---|---|
| `FILE` | **yes** | Path to the `.xlsx` workbook |
| `TITLE` | **yes** | Current tab title |
| `NEW_TITLE` | **yes** | New tab title. Must not collide with another tab |
| `--force` | no | Rename even when formulas reference the old title |

**Unlike Google Sheets, renaming here does not rewrite formulas that point at the old
title.** The command refuses when any exist, listing the offending cells:

```json
{
  "code": "invalid_input",
  "message": "refusing to rename this tab: 2 formula references to \"Source\" would be left pointing at a tab that no longer exists (Report!A1, Report!B2). Pass --force to do it anyway, then fix the references yourself.",
  "operation": "sheets.rename",
  "service": "excel"
}
```

Fix those formulas first, or pass `--force` and repair them afterwards. Named ranges and
autofilters are handled correctly and never block the command. Renaming a tab to its
current title succeeds and reports `"unchanged": true`.

---

## values get

Read cell values from a range.

```
aai-cli excel values get <FILE> <RANGE>
```

**Example**

```
aai-cli excel values get ./inventory.xlsx "'Sheet1'!A1:C3"
```

```json
{
  "file": "./inventory.xlsx",
  "range": "'Sheet1'!A1:C3",
  "majorDimension": "ROWS",
  "values": [
    ["Item", "Cost", "Stocked"],
    ["Wheel", 20.5, true],
    ["Door", 15.0, false]
  ]
}
```

---

## values update

Write cell values into the workbook, starting at the range's top-left cell.

```
aai-cli excel values update <FILE> <RANGE> --values '<JSON>' [--force]
```

| Argument/Flag | Required | Description |
|---|---|---|
| `FILE` | **yes** | Path to the spreadsheet file |
| `RANGE` | **yes** | A1 notation anchor or full range |
| `--values` | **yes** | JSON array of arrays. Each inner array is one row. |
| `--force` | no | Write even when the workbook holds features a rewrite would drop |

The payload decides how far the write extends — a bounded range does not truncate it.
JSON types map onto cell types: numbers write as numbers, booleans as booleans, strings as
text. A `null` empties that cell.

**Example**

```
aai-cli excel values update ./inventory.xlsx "'Sheet1'!A1" \
  --values '[["Item","Cost","Stocked"],["Wheel",20.5,true]]'
```

```json
{
  "file": "./inventory.xlsx",
  "updatedRange": "'Sheet1'!A1:C2",
  "updatedRows": 2,
  "updatedColumns": 3,
  "updatedCells": 6
}
```

---

## values clear

Erase cell values from a range. Formatting is preserved.

```
aai-cli excel values clear <FILE> <RANGE> [--force]
```

**Example**

```
aai-cli excel values clear ./inventory.xlsx "'Sheet1'!B2:C3"
```

```json
{
  "file": "./inventory.xlsx",
  "clearedRange": "'Sheet1'!B2:C3",
  "clearedCells": 4
}
```

`clearedCells` counts the cells that actually held a value, so it can be lower than the
size of the range.
""",
    },
]
