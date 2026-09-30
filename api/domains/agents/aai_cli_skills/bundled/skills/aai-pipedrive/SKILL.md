---
name: aai-pipedrive
description: Use aai-cli to manage Pipedrive leads, persons, organizations, deals, labels, activities, notes, deal flow/stage history, and synced mailbox data.
---

# aai-cli Pipedrive

Use this skill when working with the Pipedrive CRM through `aai-cli pipedrive`.

Before running commands, confirm the active profile or pass `--profile`. Pipedrive profiles use a personal API token (`auth_type = "pipedrive_personal_token"`); no `owner`/`repo`-style scoping is needed since a profile maps to one Pipedrive account.

For a combined view of a CRM record, prefer `deals view` / `persons view` / `organizations view` over separately calling `get` + `activities` + `notes` — it aggregates all three (plus optional email) in one response. For deal stage-transition history specifically, use `deals flow`, which surfaces `dealChange` entries with `field_key: "stage_id"`.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and real example output captured from a live Pipedrive account.
