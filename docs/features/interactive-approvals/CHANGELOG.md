# Interactive command approvals — change log

Status: Active
Epic: AF-325
Related context: [`../communications/CHANGELOG.md`](../communications/CHANGELOG.md), [`../agents.md`](../agents.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md)

## Current state

- Delivered: Slack renders clickable command-approval buttons and ingests clicks (AF-299, PR #198). The platform-neutral pieces every approval-capable plugin shares — the `approval_id` metadata key, the synthesized `action:` message-id prefix, choice labels, and the button-value codec — live in `api/domains/communications/plugins/approvals.py`. The runtime adapter keeps its own copy of the metadata key because it runs inside the Agent pod and cannot import the API; a unit test pins the two together.
- Delivered: Web Chat renders approval buttons — one per offered choice — and sends the choice with its `approval_id`. Buttons are hidden from users without `agent.update` and disabled while the Agent is not working.
- In transition: nothing.
- Next: Discord — bound the approval message under the 2000-character content limit (a live defect), then buttons and clicks.
- Blockers: Teams implementation waits on a live-tenant spike to confirm the `Action.Execute` invoke payload in personal chat, group chat and channel before any card code is written.

Every slice must hold the shared contract: one button per offered choice; the typed reply stays usable; a click arrives as an ordinary inbound message whose conversation and thread match the pending approval; the click re-passes every policy gate a typed message passes; a synthesized `action:` id is never sent to a provider as a reply reference; and ordinary sends are unchanged. None of the planned slices changes the runtime adapter, so each ships with an API deploy alone.

## Changes

### 2026-09-15 — AF-325 — Web Chat UI

- Delivered: an approval prompt becomes an assistant-ui `data` part rendered by `web-chat-approval.tsx`. Buttons come from the offered choices, never a fixed set.
- Changed: `useWebChat.sendMessage` takes an optional `approvalId`, sent only when present, so ordinary sends are unchanged. The message upsert also compares approval identity. `ChatTab` stabilises its `onSent` callback so the renderer is not re-registered on every render.
- Verified: Playwright covers a click posting `approval_id` and buttons hidden without `agent.update`; removing the permission gate makes the second test fail. The full agent-detail spec passes.
- Follow-up: Discord.

### 2026-09-15 — AF-325 — Web Chat API

- Delivered: `WebChatMessageRead.approval` on history and live-stream refreshes, read from the outbound delivery envelope — no migration. `WebChatMessageCreate.approval_id`, stored as the inbound delivery's `provider_metadata["approval_id"]` so the runtime adapter matches the answer to its pending approval.
- Changed: answering an approval uses the existing send endpoint and its Agent update permission; a viewer is refused. A stored approval that fails validation — for example one written before the identity field was renamed during AF-299 — is omitted instead of failing the thread.
- Follow-up: Web Chat UI.

### 2026-09-15 — AF-325 — Shared approval module

- Delivered: `plugins/approvals.py` with `APPROVAL_METADATA_KEY`, `SYNTHESIZED_MESSAGE_PREFIX`, `is_synthesized_message_id`, `APPROVAL_CHOICE_LABELS`, `encode_approval_value` and `decode_approval_value`.
- Changed: the Slack plugin imports these instead of defining them. No behaviour changed; the Slack plugin tests pass unmodified.
- Follow-up: Web Chat API slice.
