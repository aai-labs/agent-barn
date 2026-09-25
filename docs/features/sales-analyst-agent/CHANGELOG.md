# Sales analyst agent — change log

Status: Active
Epic: TBD
Related context: [`../integrations.md`](../integrations.md), [`../agents.md`](../agents.md), [`../templates-and-skills.md`](../templates-and-skills.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

Platform work needed to run a Pipedrive sales-analysis Agent on Agent Barn: reliable CRM scope and content retrieval, file delivery to chat, and runtime session behaviour suited to a shared, multi-user Agent. The Agent's own template and Skill are Organization content, not part of this repository.

## Current state

- Delivered: none merged yet.
- In transition: none.
- Next: publish new Platform Template versions carrying the corrected memory guidance (existing lineages are not re-seeded); the aai-cli Pipedrive work (files, field definitions, users/pipelines/stages, note and activity writes, merges, label add/remove, pagination fixes, and a credential-safe download redirect) is on an `aai-labs/aai-cli` branch pending review. It reaches Agents through a base-image rebuild, after which the bundled `aai-pipedrive` Skill copy here must be re-synced.
- Blockers: an `openclaw-base/VERSION` bump must accompany the image change below before any published rebuild.

## Changes

### 2026-09-25 — TBD — TBD

- Delivered: a Pipedrive `domain` must be a single company-subdomain label. A pasted URL or `*.pipedrive.com` host is reduced to its label; anything else is rejected, so neither the API server's validation request nor the Agent's aai-cli `base_url` can leave `*.pipedrive.com`.
- Delivered: the file-attachment instructions (`MEDIA:<absolute path>`) are appended to AGENTS.md whenever a native Slack, Discord, or Telegram Connection carries the Agent's replies, independent of mounted Skills. Previously they were emitted only with the Excel Skill, and also for gateway-only Agents, whose Connections drop attachments. The example path and the Excel block's output directory are now the runtime's own workspace; both previously named Hermes' `/workspace`, which does not exist in an OpenClaw pod.
- Follow-up: confirm in staging that native OpenClaw Slack, configured with `streaming: partial`, attaches a final-reply `MEDIA:` file; OpenClaw documents that block streaming needs structured media instead.
- Changed: `openclaw-base` installs `poppler-utils` (`pdftotext`), matching `hermes-base`, so Agents can read PDF attachments as text.
- Changed: OpenClaw Agents isolate direct messages per sender (`session.dmScope: per-channel-peer`) instead of sharing one main session across all senders. Existing Agents start fresh DM sessions after their next restart. A per-Agent session reset policy was deferred; OpenClaw's default (no automatic reset) still applies.
- Changed: the default AGENTS.md (custom-template default and predefined seed default) tells Agents to record lessons in `MEMORY.md` or a daily note. It previously pointed them at AGENTS.md, TOOLS.md, and Skills, which both runtimes rebuild from configuration on every start. Only newly created templates and newly seeded lineages pick this up.
- Follow-up: gateway-owned Slack still ignores outbound attachments; deployed environments run every Platform natively, so this only affects local and rollback configurations.
