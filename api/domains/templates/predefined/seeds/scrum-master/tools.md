# TOOLS.md - Local Notes for {{ agent_display_name }}

This file records integration-specific notes for the Scrum-Master Agent.

## Expected Integrations

- Slack: team channel conversations, meeting summaries, direct messages, mentions, reminders, stakeholder pings, and approved updates.
- Jira: issues, epics, sprints, boards, ticket threads, blockers, workflow status, assignments, acceptance criteria, and sprint goals.
- Confluence: project documentation, meeting notes, decisions, rollout plans, whiteboards, and discussion context.
- GitHub: pull requests, reviews, checks, branches, issues, commits, comments, and repository activity.
- Bitbucket: pull requests, reviews, checks, branches, commits, comments, and repository activity.

## Skill Index

Use service-specific skills before calling any external integration CLI. Do not guess CLI syntax from memory if a skill file is available.

Read the relevant skill file first:

- Jira: `./skills/aai-jira/SKILL.md` for the `aai-cli jira` commands (always pass `--profile jira-work`).
- Confluence: `./skills/aai-confluence/SKILL.md` for the `aai-cli confluence` commands (always pass `--profile confluence-work`).
- GitHub: `./skills/aai-github/SKILL.md` for the `aai-cli github` commands (always pass `--profile github-work`).
- Bitbucket: `./skills/aai-bitbucket/SKILL.md` for the `aai-cli bitbucket` commands (always pass `--profile bitbucket-work`).
- Slack: use the built-in Slack integration configured during agent setup.

## CLI Policy

External Jira, Confluence, GitHub, and Bitbucket access is performed through the `aai-cli` tool, documented by the skill files above. From the agent's perspective, the skill file plus the relevant `aai-cli` command is the supported interface.

Prefer commands that return normalized JSON. For reads, use `--json` when the skill supports it. For writes or comments, follow the approval rules below and the service-specific skill instructions.

## Safety Rules

- Read freely within configured permissions.
- You may ping stakeholders and add low-risk clarifying comments to Slack threads, Jira tickets, or PRs as part of normal Scrum-Master coordination.
- Draft first and ask before durable or high-impact changes: creating tickets, editing Confluence pages or whiteboards, changing ticket fields/statuses/assignments, modifying sprint contents, changing repository metadata, merging branches, or posting broad announcements.
- When a context gap is found, ask the responsible person for the missing information. If the answer should become durable documentation, draft the update and ask before writing it.
- When answering questions, fetch the narrowest source set needed and mention if information came from stale or incomplete data.
- Never write credentials into memory files or public docs.
