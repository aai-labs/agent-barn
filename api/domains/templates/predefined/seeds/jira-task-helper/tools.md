# TOOLS.md - Local Notes for {{ agent_display_name }}

This file records integration-specific notes for the Jira Task Helper.

## Expected Integrations

- Slack: where people talk to you — requests, clarifying questions, draft
  confirmations, and the final ticket link.
- Jira: create and update issues, set fields (project, priority, labels,
  components).

## Skill Index

Use the Jira skill before calling any external integration CLI. Do not guess CLI
syntax from memory if a skill file is available.

- Jira: `./skills/aai-jira/SKILL.md` for the `aai-cli jira` commands (always
  pass `--profile jira-work`). It covers searching/reading issues and creating
  and updating issues.

## CLI Policy

External Jira access is performed through the `aai-cli` tool, documented by the
skill file above. Prefer commands that return normalized JSON. Read the skill
file first; follow its exact command syntax.

## Safety Rules

- Reading and searching issues is free — do it to learn conventions and to find
  the right project.
- Creating or updating an issue is the job, but always show the person the draft
  and get a clear yes before you file it.
- Capture reference links and URLs in the ticket. You can't upload files or
  screenshots — if someone shares one, put any link in the description and ask
  them to attach the file to the ticket themselves. Never claim or promise an
  upload.
- Never write credentials into memory files or ticket bodies.
