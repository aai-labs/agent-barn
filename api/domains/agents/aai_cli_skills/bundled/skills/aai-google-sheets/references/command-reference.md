# aai-cli Google Sheets Skill

Agent reference for the `aai-cli sheets` command group.

## Required flag

Every command requires `--profile google-sheets-work`. Always include it.

```
aai-cli sheets <resource> <action> [args] --profile google-sheets-work
```

## Response shapes

**`spreadsheets create`** returns `spreadsheetId`, `spreadsheetUrl`, `properties.title`, and the `sheets` array for the new file. Give the user the `spreadsheetUrl`.

**`spreadsheets list`** returns a `files` array. Each element has `id` (the `spreadsheetId` used in all other commands) and `name`.

**`spreadsheets get`** returns a `sheets` array. Each element has a `properties` object with the tab `title` (use this in range strings) and numeric `sheetId`.

**`values get`** returns a `values` array of arrays. Each inner array is one row. Numbers are returned as numbers (`20.5`), not formatted strings (`"$20.50"`).

**`values update`** returns an update summary: `updatedRange`, `updatedRows`, `updatedColumns`, `updatedCells`.

**`values clear`** returns the `clearedRange`.

**`sheets add` / `sheets delete` / `sheets rename`** return the raw `batchUpdate` reply. `sheets add` includes the new tab's `sheetId` under `replies[0].addSheet.properties`.

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

## spreadsheets create

Create a new spreadsheet in the authenticated user's Drive.

```
aai-cli sheets spreadsheets create <TITLE> [--sheets A,B,C] --profile google-sheets-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `TITLE` | **yes** | Title for the new spreadsheet |
| `--sheets` | no | Comma-separated tab names. Omit for a single default `Sheet1` |

**Example**

```
aai-cli sheets spreadsheets create "Q3 Forecast" --sheets "Summary,Detail" --profile google-sheets-work
```

```json
{
  "spreadsheetId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
  "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit",
  "properties": { "title": "Q3 Forecast" },
  "sheets": [
    { "properties": { "sheetId": 0, "title": "Summary" } },
    { "properties": { "sheetId": 1, "title": "Detail" } }
  ]
}
```

Write into it with `values update` using the returned `spreadsheetId`, and give the user the `spreadsheetUrl`.

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

## sheets add

Add a tab to an existing spreadsheet.

```
aai-cli sheets sheets add <SPREADSHEET_ID> <TITLE> --profile google-sheets-work
```

| Argument | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID |
| `TITLE` | **yes** | Title for the new tab. Must not already exist |

**Example**

```
aai-cli sheets sheets add 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms "Q4" --profile google-sheets-work
```

---

## sheets delete

Delete a tab by title.

```
aai-cli sheets sheets delete <SPREADSHEET_ID> <TITLE> --profile google-sheets-work
```

The last remaining tab cannot be deleted — a spreadsheet must keep at least one.

---

## sheets rename

Rename a tab. Google updates formulas that reference the old title.

```
aai-cli sheets sheets rename <SPREADSHEET_ID> <TITLE> <NEW_TITLE> --profile google-sheets-work
```

| Argument | Required | Description |
|---|---|---|
| `SPREADSHEET_ID` | **yes** | The spreadsheet ID |
| `TITLE` | **yes** | Current tab title |
| `NEW_TITLE` | **yes** | New tab title. Must not collide with another tab |

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
