# Interactive command approvals — change log

Status: Active
Epic: AF-325
Related context: [`../communications/CHANGELOG.md`](../communications/CHANGELOG.md), [`../agents.md`](../agents.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md)

## Current state

- Delivered: Slack renders clickable command-approval buttons and ingests clicks (AF-299, PR #198). The platform-neutral pieces every approval-capable plugin shares — the `approval_id` metadata key, the synthesized `action:` message-id prefix, and the button-value codec — live in `api/domains/communications/plugins/approvals.py`; offered choice labels travel in the `ApprovalRequest` contract. The runtime adapter keeps its own copy of the metadata key because it runs inside the Agent pod and cannot import the API; a unit test pins the two together.
- Delivered: Web Chat renders approval buttons — one per offered choice — and sends the choice with its `approval_id`. Buttons are hidden from users without `agent.update`, disabled while the Agent is not working, and disabled once the approval is answered in that browser session (re-enabled if the answer fails to send).
- In transition: nothing.
- Delivered: Discord renders approval buttons, ingests clicks, removes the buttons once an accepted click is answered, and keeps its prompt under the 2,000-character content limit.
- Next: Telegram — baseline `normalize_inbound` tests and explicit `allowed_updates`, then buttons and clicks.
- Blockers: Teams implementation waits on a live-tenant spike to confirm the `Action.Execute` invoke payload in personal chat, group chat and channel before any card code is written.

Every slice must hold the shared contract: one button per offered choice; the typed reply stays usable; a click arrives as an ordinary inbound message whose conversation and thread match the pending approval; the click re-passes every policy gate a typed message passes; a synthesized `action:` id is never sent to a provider as a reply reference; and ordinary sends are unchanged. None of the planned slices changes the runtime adapter, so each ships with an API deploy alone.

## Changes

### 2026-09-16 — AF-325 — Discord buttons fit inside the identifier limit

- Observed: the first live test in auto mode showed the prompt with no buttons. A button identifier carries the conversation, the approval identity and the choice, and Discord caps it at 100 characters; with real identifiers the `session` button reached 101, so the encoder's own guard dropped every button and the message went out as text. `once` and `deny` fit at 98, so manual mode would have looked correct — and the unit tests used short fixtures, so they stayed green.
- Changed: the identifier is now compact — a two-character prefix and one-letter choice codes expanded back on the way in — which brings the worst case to 79. Choices the runtime invents are still carried whole.
- Changed: three layers now stand between a longer identifier and a prompt without buttons. If the value would not fit, the conversation is dropped from it and taken from the message the button sits on instead, which is the message that started the run. Only if that still does not fit are the buttons omitted, and that now logs a warning instead of failing silently. A conversation that cannot be recovered ends in a refusal, never a wrong approval.
- Verified: a test builds a prompt from real-shaped identifiers and asserts buttons are rendered; a budget test derives the longest identifier the constants can produce and fails if anyone lengthens them. Both fail against the code that shipped the defect. Round-trip tests cover every choice, an invented one, and another app's value.
- Follow-up: Telegram, whose limit is 64 bytes and which reuses this encoding.

### 2026-09-16 — AF-325 — Discord buttons and clicks

- Delivered: a Discord approval prompt carries one button per offered choice, chunked into rows of five since a row holds no more. A click arrives as an ordinary inbound answer carrying its `approval_id`, and the conversation it lands in comes from the button itself, so it always matches the run that is waiting.
- Delivered: the ingress forwards component interactions, which it previously dropped, and acknowledges each one over HTTP before persisting it, inside Discord's three-second deadline. An accepted click's acknowledgement also removes the buttons, so the same approval cannot be answered twice; a click that policy refuses is acknowledged without touching the message, so an outsider cannot strip the buttons from the people allowed to use them.
- Changed: a click re-passes the server, channel, user, role and direct-message gates a typed message passes — the same code, in the same order — and the @mention requirement is replaced by proof the button sits on a message this Agent posted. A reply to a click no longer quotes the click's synthesized id, which Discord would reject.
- Changed: a button value that would exceed Discord's 100-character identifier limit sends the prompt without buttons instead of failing the send.
- Verified: unit tests cover each gate, the button set, the row split, the identifier limit, the reply reference, and the ingress path against a real websocket server — acknowledgement before persistence, and type 6 rather than 7 for a refused click. Removing any one of those guards fails its test. The Slack and Web Chat suites are unchanged and green.
- Follow-up: Telegram.

### 2026-09-16 — AF-325 — Discord approval prompts fit the message limit

- Observed: Discord caps a message at 2,000 characters and the approval prompt reaches 2,538 for the longest command the runtime sends, so that send returned 400, retried and dead-lettered — blocking the conversation. A test reproduced the 2,538-character content before the fix.
- Delivered: Discord renders its own approval content, bounding the command the way Slack bounds its section block and reporting how many characters are hidden.
- Changed: the fallback line names the message to answer — "Or reply to your original request with one of: …" — because a Discord conversation is keyed by the message that started it, so a new message or a reply to the prompt itself reaches a different session and cannot resolve the waiting command. Buttons, which carry the right conversation, are the real fix and land next.
- Verified: the bounded content stays under the limit and still names every offered choice; an ordinary reply is passed through byte-for-byte.
- Follow-up: Discord buttons and clicks.

### 2026-09-15 — AF-325 — Web Chat buttons disable once answered

- Observed: in a live test the buttons stayed clickable after answering, so each extra click posted another choice and got "No command is waiting for approval."
- Changed: `WebChatApprovalRenderer` tracks answered approval ids. A click disables every button for that approval before sending; a failed send re-enables them. The state is client-side only, so a page reload re-enables old prompts, and the runtime adapter still refuses those clicks.
- Verified: Playwright covers one POST per clicked approval with all its buttons disabled, and re-enabling after a failed send; removing the re-enable makes that test fail. The full agent-detail spec passes.
- Follow-up: Discord.

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

- Delivered: `plugins/approvals.py` with `APPROVAL_METADATA_KEY`, `SYNTHESIZED_MESSAGE_PREFIX`, `is_synthesized_message_id`, `encode_approval_value` and `decode_approval_value`; `ApprovalRequest.choice_labels` supplies display labels to each platform.
- Changed: the Slack plugin imports these instead of defining them. No behaviour changed; the Slack plugin tests pass unmodified.
- Follow-up: Web Chat API slice.
