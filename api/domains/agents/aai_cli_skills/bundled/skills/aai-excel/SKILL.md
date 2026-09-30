---
name: aai-excel
description: Use aai-cli to create local spreadsheet files, manage their sheet tabs, and read, update, or clear cell values — Excel (.xlsx/.xlsm) and delimited text (.csv/.tsv).
---

# aai-cli Excel

Use this skill when working with spreadsheet files on disk through `aai-cli excel`.

Read and write `.xlsx`, `.xlsm`, `.csv`, `.tsv`. Read-only: `.xls` (Excel 97–2003), `.xlsb`, `.ods` — to edit one, save it as `.xlsx` or `.csv` first.

These are local files. There is no account, profile, or credential involved — do **not** pass `--profile`, and do not ask the user to authenticate. Just point the command at a file path.

Use `workbook create` to start a new file, `sheets list` to discover tab names and how far each one's data extends, `sheets add`/`delete`/`rename` to change the tabs of an existing `.xlsx`, then `values` commands to read, update, or clear ranges.

Ranges use A1 notation and accept the same forms as Google Sheets: `'Sheet1'!A1:D5`, a single cell, an open column range (`B:C`), an open row range (`2:5`), or a bare sheet name for everything in use. `values update` expects `--values` as a JSON array of row arrays, and writes starting at the range's top-left cell.

A `.csv`/`.tsv` file is a single sheet named after the file (`sales.csv` → `sales`), so `--sheets` does not apply when creating one and the `sheets add`/`delete`/`rename` commands do not either.

Tab names follow Excel's rules: at most 31 characters, and never `: \ / ? * [ ]`. A workbook must keep at least one tab.

**Renaming or deleting a tab does not update formulas that point at it.** If any formula references the tab, the command is **refused** with the offending cells listed; either fix those formulas first, or pass `--force` and repair them afterwards. Named ranges and autofilters are handled correctly and never block the command.

**Editing an `.xlsx` rewrites the whole workbook**, which cannot preserve charts, pivot tables, form controls, external links, custom XML or sensitivity labels. Writes to such a workbook are **refused** with a message naming what would be lost; pass `--force` only if losing those is genuinely acceptable, or copy the values into a new file instead. Plain data workbooks are unaffected.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and examples.
