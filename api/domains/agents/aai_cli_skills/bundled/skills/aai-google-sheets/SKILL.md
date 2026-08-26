---
name: aai-google-sheets
description: Use aai-cli to create Google Sheets spreadsheets, manage their tabs, and read, update, or clear cell values.
---

# aai-cli Google Sheets

Use this skill when working with Google Sheets through `aai-cli sheets`.

Always pass the intended Google Sheets profile with `--profile` unless the active default profile is already known. Use `spreadsheets create` to make a new spreadsheet, `spreadsheets list` to find spreadsheet IDs, `spreadsheets get` to inspect tab titles, `sheets` commands to add, delete, or rename tabs, and `values` commands to read, update, or clear ranges.

Address tabs by their title — `sheets delete` and `sheets rename` look up the numeric `sheetId` for you.

Use A1 notation ranges. `values update` expects `--values` as a JSON array of row arrays.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and examples.
