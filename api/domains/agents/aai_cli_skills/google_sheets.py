"""aai-cli google sheets skill docs."""

GOOGLE_SHEETS_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/google_sheets_skill.md",
        "skill_content": r"""\
# aai-cli Google Sheets Skill

Agent reference for the `aai-cli sheets` command group.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, site URLs,
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flag

Every command requires `--profile google-sheets-work`. Always include it.

```
aai-cli sheets <resource> <action> [args] --profile google-sheets-work
```

## Response shapes

**`spreadsheets list`** returns a `files` array. Each element has `id` (the `spreadsheetId` used in all other commands) and `name`.

**`spreadsheets get`** returns a `sheets` array. Each element has a `properties` object with the tab `title` (use this in range strings) and numeric `sheetId`.

**`values get`** returns a `values` array of arrays. Each inner array is one row. Numbers are returned as numbers (`20.5`), not formatted strings (`"$20.50"`).

**`values update`** returns an update summary: `updatedRange`, `updatedRows`, `updatedColumns`, `updatedCells`.

**`values clear`** returns the `clearedRange`.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "error": { "code": 403, "message": "..." } },
  "message": "provider returned HTTP 403",
  "operation": "values.get",
  "service": "sheets",
  "status": 403
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Google returned 4xx/5xx. Check `status` and `details.error.message` |
| `auth` | Missing or invalid token |
| `invalid_input` | A required flag or argument was missing or malformed |
| `network` | Could not reach Google APIs |

Exit code is non-zero on any error.

---

## spreadsheets list

List all Google Sheets spreadsheets in the authenticated user's Drive. Returns 25 per page.

```
aai-cli sheets spreadsheets list [--page-token TOKEN] --profile google-sheets-work
```

| Flag | Required | Description |
|---|---|---|
| `--page-token` | no | `nextPageToken` from a previous response to fetch the next page |

**Example**

```
aai-cli sheets spreadsheets list --profile google-sheets-work
```

```json
{
  "files": [
    { "id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms", "name": "Agent Task Tracker" },
    { "id": "1k9c6R3XwFm4oZQL8sNVqC5ZdPJHgaLmiBuTeUr9dkbY", "name": "Inventory 2026" }
  ],
  "nextPageToken": "~!!~AI9FV7..."
}
```

The `id` field is the `spreadsheetId` used in all subsequent commands. If `nextPageToken` is present, pass it as `--page-token` to fetch the next page.

---

## spreadsheets get

Get the tab structure of a spreadsheet.

```
aai-cli sheets spreadsheets get <SPREADSHEET_ID> --profile google-sheets-work
```

| Argument | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID (from `spreadsheets list` or the Drive URL) |

**Example**

```
aai-cli sheets spreadsheets get 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms --profile google-sheets-work
```

```json
{
  "sheets": [
    { "properties": { "sheetId": 0, "title": "Sheet1" } },
    { "properties": { "sheetId": 815649284, "title": "Inventory" } }
  ]
}
```

Use the `title` value to construct range strings (e.g. `'Inventory'!A1:D10`).

---

## values get

Read cell values from a range.

```
aai-cli sheets values get <SPREADSHEET_ID> <RANGE> --profile google-sheets-work
```

| Argument | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID |
| `RANGE` | **yes** | A1 notation range, e.g. `'Sheet1'!A1:D5` |

**Example**

```
aai-cli sheets values get 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms "'Sheet1'!A1:D5" --profile google-sheets-work
```

```json
{
  "range": "'Sheet1'!A1:D5",
  "majorDimension": "ROWS",
  "values": [
    ["Item", "Cost", "Stocked"],
    ["Wheel", 20.5, 4],
    ["Door", 15, 2]
  ]
}
```

---

## values update

Write cell values to a range.

```
aai-cli sheets values update <SPREADSHEET_ID> <RANGE> --values '<JSON>' --profile google-sheets-work
```

| Argument/Flag | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID |
| `RANGE` | **yes** | A1 notation top-left anchor or full range |
| `--values` | **yes** | JSON array of arrays. Each inner array is one row. |

**Example**

```
aai-cli sheets values update 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms "'Sheet1'!A1" \
  --values '[["Item","Cost"],["Wheel",20.5]]' \
  --profile google-sheets-work
```

```json
{
  "spreadsheetId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  "updatedRange": "'Sheet1'!A1:B3",
  "updatedRows": 2,
  "updatedColumns": 2,
  "updatedCells": 4
}
```

---

## values clear

Erase cell values from a range. Formatting is preserved.

```
aai-cli sheets values clear <SPREADSHEET_ID> <RANGE> --profile google-sheets-work
```

| Argument | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID |
| `RANGE` | **yes** | A1 notation range to clear |

**Example**

```
aai-cli sheets values clear 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms "'Sheet1'!A2:B3" --profile google-sheets-work
```

```json
{
  "spreadsheetId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  "clearedRange": "'Sheet1'!A2:B3"
}
```
""",
    },
]
