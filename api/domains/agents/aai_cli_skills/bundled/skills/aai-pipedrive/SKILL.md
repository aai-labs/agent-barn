---
name: aai-pipedrive
description: Use aai-cli to manage Pipedrive leads, persons, organizations, deals, labels, activities, notes, file attachments, field definitions, users, pipelines and stages, deal flow/stage history, and synced mailbox data.
---

# aai-cli Pipedrive

Use this skill when working with the Pipedrive CRM through `aai-cli pipedrive`.

Before running commands, confirm the active profile or pass `--profile`. Pipedrive profiles use a personal API token (`auth_type = "pipedrive_personal_token"`); no `owner`/`repo`-style scoping is needed since a profile maps to one Pipedrive account.

For a combined view of a CRM record, prefer `deals view` / `persons view` / `organizations view` over separately calling `get` + `activities` + `notes` — it aggregates all three (plus optional email) in one response. For deal stage-transition history specifically, use `deals flow`, which surfaces `dealChange` entries with `field_key: "stage_id"`.

Meeting transcripts and other documents are usually file attachments, not notes. List them with `files list --deal-id` / `--person-id` / `--org-id` and fetch each with `files download <id> --output PATH`, then convert it to text before reading.

Record payloads refer to custom fields by hash key and to option values (Industry, custom dropdowns) by numeric ID. Resolve them with `fields <deals|persons|organizations> list` before matching records by a field's name or value.

List commands stop at `--limit` (usually 50). When `_aai.pagination.status` is `more_available`, the result is partial — raise `--limit` before counting or summarizing records.

When editing labels, `--label-ids` replaces every label on the record; use `--add-label-ids` / `--remove-label-ids` to change one without dropping the rest. `merge` keeps the `--merge-with-id` record and cannot be undone.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and real example output captured from a live Pipedrive account.
