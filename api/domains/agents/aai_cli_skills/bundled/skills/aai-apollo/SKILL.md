---
name: aai-apollo
description: Use aai-cli to search Apollo people and organizations, enrich records, manage contacts/accounts/deals, inspect outreach activity, and work with sequences, emails, tasks, calls, and reporting inputs.
---

# aai-cli Apollo

Use this skill when working with Apollo through `aai-cli apollo`.

Before running commands, confirm the active profile or pass `--profile`. Apollo profiles use API-key auth (`auth_type = "apollo_api_key"`) with `api_token_secret`.

Apollo keeps discovery records and saved records separate. Use `people` and `organizations` commands for sourcing and enrichment; use `contacts`, `accounts`, and `deals` commands for saved Apollo CRM/workflow records.

For Sally-style sales workflows, treat Apollo as the source for sourcing, enrichment, sequence membership, and Apollo-run outreach activity. Do not treat Apollo as the final CRM unless the task explicitly says so. If respondents are handed into Pipedrive manually, call that out clearly.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and real example output captured from a live Apollo account.
