# Sales analyst agent — change log

Status: Active
Epic: AF-352
Related context: [`../integrations.md`](../integrations.md), [`../agents.md`](../agents.md), [`../templates-and-skills.md`](../templates-and-skills.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

Platform work needed to run a Pipedrive sales-analysis Agent on Agent Barn: reliable CRM scope and content retrieval, file delivery to chat, and runtime session behaviour suited to a shared, multi-user Agent. The Agent's own template and Skill are Organization content, not part of this repository.

## Current state

- Delivered: nothing merged yet. aai-labs/agent-barn#252 delivers the changes listed below once merged.
- In transition: none.
- Next: publish new Platform Template versions carrying the corrected memory guidance (existing lineages are not re-seeded); the aai-cli Pipedrive work (files, field definitions, users/pipelines/stages, note and activity writes, merges, label add/remove, pagination fixes, and a credential-safe download redirect) is in review as aai-labs/aai-cli#26 (AF-353). It reaches Agents through a base-image rebuild, after which the bundled `aai-pipedrive` Skill copy here must be re-synced.
- Blockers: `staging` already uses `openclaw-base` 0.7.2 for different contents, so after merging `staging` into this branch, `openclaw-base/VERSION` must become 0.7.3 (runtime versions are never reused). Before deploying, run `python -m api.scripts.check_secret_contents` in each environment's API pod (see below).

## Changes

### 2026-10-01 — AF-354 — aai-labs/agent-barn#252

- Delivered: a Pipedrive `domain` must be a single company-subdomain label. A pasted URL or `*.pipedrive.com` host is reduced to its label; anything else is rejected, so neither the API server's validation request nor the Agent's aai-cli `base_url` can leave `*.pipedrive.com`.
- Changed: stored integration content is re-validated on every start, so content saved before a rule tightened (such as a multi-label Pipedrive domain) now stops the start with a 400 that names the integration and asks for it to be saved again; the Agent keeps its status. Creating an Agent with such a shared credential likewise returns a 400 naming the shared credential. `python -m api.scripts.check_secret_contents` lists stored Agent Secrets and Shared Credentials that would fail, without printing their values. No local rows failed.
- Delivered: the file-attachment instructions (`MEDIA:<absolute path>`) are appended to AGENTS.md whenever a native Slack, Discord, or Telegram Connection carries the Agent's replies, independent of mounted Skills. Previously they were emitted only with the Excel Skill, and also for gateway-only Agents, whose Connections drop attachments. The example path is now the runtime's own workspace; it previously named Hermes' `/workspace`, which does not exist in an OpenClaw pod. The Excel tools block no longer repeats where to write shared files; the delivery block owns that. Each runtime's workspace path is one constant (`HERMES_WORKSPACE_DIR`, `OPENCLAW_WORKSPACE_DIR`) used by its builder, the OpenClaw config (`agents.defaults.workspace`), the legacy-workspace migration script, and the delivery policy.
- Follow-up: confirm in staging that native OpenClaw Slack, configured with `streaming: partial`, attaches a final-reply `MEDIA:` file. It does on a local k3d Agent with a GPT-class model; OpenClaw documents that block streaming needs structured media instead.
- Changed: `openclaw-base` installs `poppler-utils` (`pdftotext`), matching `hermes-base`, so Agents can read PDF attachments as text. `ffmpeg` is deliberately not added (about 0.7 GB for every Agent); an Agent that needs it installs a pinned static build on its persistent volume at first use.
- Changed: native OpenClaw Slack accepts inbound files up to 100 MB (`channels.slack.mediaMaxMb`); OpenClaw's 20 MB default dropped meeting recordings (an hour of MP3 is ~60-90 MB) before the Agent saw them. Verified locally with a ~50 MB recording on a 1 GiB pod.
- Follow-up: upload a ~90 MB file in staging to confirm the 1 GiB pod limit holds near the new ceiling.
- Changed: OpenClaw Agents isolate direct messages per sender (`session.dmScope: per-channel-peer`) instead of sharing one main session across all senders. Existing Agents start fresh DM sessions after their next restart. A per-Agent session reset policy was deferred; OpenClaw's default (no automatic reset) still applies.
- Changed: the default AGENTS.md (custom-template default and predefined seed default) tells Agents to record lessons in `MEMORY.md` or a daily note. It previously pointed them at AGENTS.md, TOOLS.md, and Skills, which both runtimes rebuild from configuration on every start. Only newly created templates and newly seeded lineages pick this up.
- Follow-up: gateway-owned Slack still ignores outbound attachments; deployed environments run every Platform natively, so this only affects local and rollback configurations.
