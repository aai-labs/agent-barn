---
name: aai-confluence
description: Use aai-cli to inspect and manage Confluence spaces, pages, comments, attachments, and page moves.
---

# aai-cli Confluence

Use this skill when working with Confluence Cloud through `aai-cli confluence`.

Before running commands, confirm the active profile or pass `--profile`. Prefer typed commands for spaces, pages, comments, attachments, and page moves; use `confluence request` only for uncommon Confluence REST endpoints.

List commands aggregate pagination up to `--limit` and return trimmed provider envelopes. Get commands return full raw provider responses.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and examples.
