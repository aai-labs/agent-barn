---
name: aai-jira
description: Use aai-cli to search and manage Jira issues, Jira Product Discovery ideas, projects, boards, sprints, comments, and attachments.
---

# aai-cli Jira

Use this skill when working with Jira Cloud through `aai-cli jira`.

Before running commands, confirm the active profile or pass `--profile`. Prefer typed commands for common issue, idea, sprint, board, project, comment, and attachment workflows; use `jira request` only for uncommon Jira REST endpoints.

For Jira Product Discovery, use `jira ideas` commands: they scope searches to Product Discovery projects, default the create issue type to `Idea`, and discover project-specific idea fields (`jira ideas fields PROJECT`) so custom fields like Impact or Effort can be set through `--json`.

List commands aggregate Jira pagination up to `--limit` and preserve the documented response shape. Create and update commands accept typed flags and, where documented, `--json` payloads.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for filters, payload rules, response shapes, and examples.
