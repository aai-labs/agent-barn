# Communications plugins and gateway — change log

Status: Active
Epic: Communications plugin architecture
Related context: [Agents](../agents.md), [Activity and Ingest](../activity-and-ingest.md), [Runtime and Deployment](../../architecture/runtime-and-deployment.md), [gateway ownership ADR](../../adr/2026-08-22-agent-barn-owned-communications-gateway.md)

## Current state

- Delivered: Agent-subordinate Communication Connection persistence and scoped CRUD; explicit shipped Platform Plugin registry; Slack, Telegram, and Discord plugins; strict plugin-owned settings/credential schemas; encrypted credential envelopes; generic credential uniqueness; optimistic concurrency; platform catalogue; connection-scoped canonical Conversation Messages; durable inbound/outbound Communication Deliveries; gateway-supervised Slack Socket Mode, Telegram polling, and Discord Gateway ingress; database ingress leases; a separately served gateway; one versioned runtime-neutral protocol used by both runtimes; Slack channel/thread mention admission with durable Connection-scoped thread ownership; provider-neutral processing feedback with Slack reactions and assistant thread status; bounded adaptive idle claim backoff shared by both runtime adapters; and an optional, best-effort Platform Plugin seam that resolves missing sender/channel names through cached provider lookups before persistence.
- Changed: Agents are headless and no longer own a single Platform. Legacy provider configuration tables, DTO fields, routes, and provider-specific UI have been removed after their data is migrated into Communication Connections.
- Next: add Agent Barn Chat as another adapter at the Platform Plugin seam, then evaluate iMessage transport constraints independently of Agent runtimes.
- Blockers: none.

## Changes

### 2026-08-25 — Provider setup guidance — PR pending

- Changed: Platform descriptors now expose optional provider-owned setup hints in the schema-driven Connection form. Slack's hint lists the directory scopes needed for channel, DM, and sender-name resolution and reminds users to reinstall the app after changing scopes.

### 2026-08-25 — AF-272 — Restore communication sender/channel names — PR pending

- Delivered: An optional `enrich_inbound` Platform Plugin seam resolves missing sender and channel/DM display names through cached, credential-scoped provider lookups (Slack user/channel/DM directory, Discord user/channel lookups, Telegram chat lookups) before durable persistence. `CommunicationsGatewayService` invokes it once at the single point all three ingress paths (supervised provider ingress, driver events, webhook events) already share, so no route duplicates the call. A provider payload's own names are always preferred; enrichment only fills what's missing, and any lookup failure falls back to the envelope as normalized rather than delaying or rejecting acceptance.
- Changed: `CommunicationDeliveryRepository.accept_inbound` now backfills `sender_name`/`channel_name` on a duplicate provider delivery via `COALESCE`, so a retry can supply a name the first attempt lacked, but a duplicate can never clear a name already known. `ConversationRepository.upsert_messages` got the same `COALESCE` fix. Runtime outbound replies now inherit `channel_name` from their source inbound envelope's location. The Telegram chat-name cache key is now scoped by a hash of the bot token, matching Discord's existing per-token scoping, so two Connections can no longer share a cached name for the same provider-global chat/user ID. Message identity, delivery ordering/retries, and credential isolation are unchanged.
- Follow-up: none. Hermes/OpenClaw telemetry plugins intentionally remain untouched — they own Tool Call telemetry only; Conversation Message names are resolved solely at the Platform Plugin seam.

### 2026-08-24 — AF-272 — Bounded runtime claim backoff — PR pending

- Delivered: The shared Hermes/OpenClaw Communications adapter now exponentially backs off empty claim responses from 500 ms to a bounded 5-second cadence with jitter, then resets immediately after a delivery is claimed.
- Changed: Idle cadence is client-side; no new server/database polling loop or protocol version was introduced. Claim ordering, leases, retries, idempotency, and shutdown/error handling remain unchanged.
- Follow-up: Communications cutover slices are complete; next platform work can proceed at the Platform Plugin seam.

### 2026-08-24 — AF-272 — Slack processing feedback — PR pending

- Delivered: Accepted Slack messages receive an immediate 👀 reaction; claimed deliveries show a Slack assistant processing status; successful outbound provider delivery replaces 👀 with ✅; terminal runtime/provider failure clears status, removes 👀, and adds ❌.
- Changed: Added the provider-neutral processing-feedback capability and lifecycle seam. Slack's calls use existing `chat:write` and `reactions:write` scopes, target reactions by the canonical message timestamp, treat duplicate reaction state as success, and remain best-effort so feedback cannot alter durable delivery outcomes.
- Follow-up: Replace idle runtime claim polling with bounded long polling/backoff.

### 2026-08-24 — AF-272 — Slack mention and thread admission — PR pending

- Delivered: Slack channel messages now require a direct bot mention. The schema-driven `thread_mention_policy` setting supports conservative `every_message` admission and conversational `start_only` admission for unmentioned replies in Agent-owned threads.
- Changed: Slack ingress captures the bot user ID, rejects bot/edit events, and consumes only normalized `message` events to avoid duplicate `app_mention` deliveries. Thread ownership is resolved through persisted Connection-scoped Conversation Message state via the provider-neutral plugin admission seam.
- Follow-up: Restore provider-neutral processing feedback, then replace idle runtime claim polling with bounded long polling/backoff.

### 2026-08-22 — Hard cutover to communications plugins and gateway — PR pending

- Delivered: generic Agent-owned Communication Connections, multiple same-platform connections, the code-owned plugin catalogue, shipped Slack/Telegram/Discord plugins, credential encryption/fingerprints, safe read projections, complete schema-driven create/edit management, Agent-permission authorization, optimistic concurrency, retirement, connection-scoped conversation reads, durable delivery workers, supervised provider ingress with replica-safe leases, and runtime protocol adapters.
- Removed: the incomplete Microsoft Teams plugin and its legacy multi-tenant authentication path. A future Teams plugin must be designed around Microsoft's supported single-tenant identity model before it is shipped.
- Changed: migrated existing provider configuration and attributable messages, removed the single-platform Agent schema and native runtime transport branching, and replaced provider-specific Agent forms with schema-driven Connection management.
