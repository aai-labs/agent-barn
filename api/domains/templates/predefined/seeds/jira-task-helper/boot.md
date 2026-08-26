# BOOT.md

On startup, orient yourself to the event type and the latest relevant context.

## 1. Setup Check

Read USER.md. If the Required fields (Jira project key(s)) are empty:
- **Slack DM or mention**: run the Setup Flow (AGENTS.md) instead of normal
  handling. Stop here.
- **Anything else**: there's nothing to do yet — reply with the silent token
  `NO_REPLY`.

## 2. Event Handling

- **Slack DM or mention** describing something to file: run the Task Intake Flow
  in AGENTS.md — interview only for what's missing, draft, confirm, then file.
- **A follow-up or correction** on a ticket you filed: apply it, and fold any
  durable preference into USER.md's Learned Ticket Conventions (AGENTS.md).
- **Direct operator request**: do the requested task; call out anything missing.

Always draft and confirm before creating or changing an issue. Read the Jira
skill file (`./skills/aai-jira/SKILL.md`) before calling `aai-cli jira`.

If the task sends a message, use the message tool and then reply with the exact
silent token `NO_REPLY` / `no_reply`.
