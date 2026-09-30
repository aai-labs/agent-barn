---
name: aai-google-drive
description: Use aai-cli to find Google Drive files and folders, read their metadata, download their content (including Google-native Docs, Sheets, and Slides), check who a file is shared with, and upload a local file back to Drive.
---

# aai-cli Google Drive

Use this skill when working with Google Drive through `aai-cli drive`.

Before running commands, confirm the active profile or pass `--profile`. Drive profiles are ordinary Google REST profiles (`provider = "google"`, `auth_type = "bearer_token"`), the same shape as Gmail, Calendar, and Sheets.

This arm is read-first. `files upload` is the one write: it creates a new Drive file from local bytes. Nothing here changes sharing, renames, moves, trashes, or deletes — and `permissions` is read-only on purpose, so an agent cannot widen who can see a file.

Start from `files list` (or `folders list`) to turn a name into a file ID, then `files get` for full metadata and `files download` for content. `--parent <folder-id>` scopes a listing to one folder; `--drive-id <id>` scopes it to one shared drive. Shared-drive content is included by default.

`files download` writes to `--output` and never prints content to stdout. Google-native documents have no bytes of their own, so they are exported instead: Docs to `.docx`, Sheets to `.xlsx`, Slides to `.pptx`, other native types to PDF. Pass `--mime-type` to choose a different conversion. Exports are capped at 10 MB by Google, and native documents report no `size`, so that cap only shows up as an error.

For cell-level work on a Google Sheet, use the `aai-cli sheets` commands instead of downloading the file.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, flags, response notes, and examples.
