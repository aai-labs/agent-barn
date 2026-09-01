# Communications plugins and gateway — change log

Status: Active
Epic: Communications plugin architecture
Related context: [Agents](../agents.md), [Activity and Ingest](../activity-and-ingest.md), [Runtime and Deployment](../../architecture/runtime-and-deployment.md), [gateway ownership ADR](../../adr/2026-08-22-agent-barn-owned-communications-gateway.md)

## Current state

- Delivered: Agent-subordinate Communication Connection persistence and scoped CRUD; explicit shipped Platform Plugin registry; Slack, Telegram, Discord, and Microsoft Teams plugins; the first webhook-ingress platform, authenticated by Bot Framework JWT verification at the `verify_webhook` seam; strict plugin-owned settings/credential schemas; encrypted credential envelopes; generic credential uniqueness; optimistic concurrency; platform catalogue; connection-scoped canonical Conversation Messages; durable inbound/outbound Communication Deliveries; gateway-supervised Slack Socket Mode, Telegram polling, and Discord Gateway ingress; database ingress leases; a separately served gateway; one versioned runtime-neutral protocol used by both runtimes; Slack channel/thread mention admission with durable Connection-scoped thread ownership; provider-neutral processing feedback with Slack reactions and assistant thread status; bounded adaptive idle claim backoff shared by both runtime adapters; and an optional, best-effort Platform Plugin seam that resolves missing sender/channel names through cached provider lookups before persistence.
- Changed: Agents are headless and no longer own a single Platform. Legacy provider configuration tables, DTO fields, routes, and provider-specific UI have been removed after their data is migrated into Communication Connections.
- Next: add Agent Barn Chat as another adapter at the Platform Plugin seam, then evaluate iMessage transport constraints independently of Agent runtimes. Email is delivered for inbound and reply; agent-initiated outbound remains unbuilt.
- Blockers: none.

## Changes

### 2026-08-31 — AF-276 — Email as a communication platform — PR pending

- Delivered: A shipped Email Platform Plugin, the first platform reached at an address rather than through a per-Connection endpoint. Each Email Connection is allocated `agent+<slug>-<token>@<AGENT_EMAIL_DOMAIN>`, claimed on create and released on retirement or Agent deletion, with the local part never reissued. A Cloudflare Email Worker parses inbound MIME and posts to `POST /communications/v1/webhooks/email/inbound`, authenticated by a gateway-level shared secret because the Worker knows only the recipient address, never a Connection id. Replies are plain text, sent from the Agent's own address, threaded on the References root.
- Changed: `PlatformCapability` gained `MANAGED_ADDRESS`, which now also suppresses the per-Connection `webhook_url` — Email declares `WEBHOOK_INGRESS` only so `PlatformIngressSupervisor` parks it instead of polling, and the URL it implied was meaningless for a mailbox-addressed platform. `CommunicationPlatform` gained `EMAIL` so the platform-admin stats filter can see these Connections. `CommunicationConnectionRepository.create` takes an optional address allocator and claims inside the Connection's transaction, retrying local-part collisions in a savepoint. `Email`/`EmailClient` gained a per-message sender address, plain-text part, `Reply-To` and custom headers.
- Notes: Scope is **inbound and reply only**. `RuntimeReplyCreate` has no recipient field and `enqueue_runtime_reply` copies the location from the source inbound delivery, so an Agent structurally cannot address anyone who did not write to it first; a test pins this. Inbound email is untrusted text reaching the LLM, and unlike every other platform it needs no channel membership — mitigated by an allowlist that defaults to empty, an address Agent Barn never publishes, and the sender-only reply property.
- Notes: Cloudflare's send API returns no message id, so threads anchor on the References root rather than on our own `Message-ID`, which we can never learn. Email Workers cannot read SPF/DKIM/DMARC verdicts (cloudflare/workerd#6740); Cloudflare's MX rejects DMARC failures upstream, and sender trust beyond that is the Connection allowlist.
- Follow-up: agent-initiated ("cold") outbound needs a gateway path for an outbound delivery with no source delivery, plus a way for a runtime to invoke it — no tool or MCP surface exists today. Attachments, HTML replies, CC/BCC, processing feedback, and bounce handling are all unimplemented. The Worker deploys manually with `wrangler` and has no CI coverage. `prepare_communications_server` now exists, so the Teams provider webhook route can finally get the integration coverage this log recorded as missing.

### 2026-08-28 — AF-118 — Harden the Teams authentication path — PR pending

- Delivered: Inbound Bot Framework tokens are now bound to the activity they arrive with. `verify_inbound_jwt` requires the `serviceurl` claim and matches it against the activity's `serviceUrl`, ignoring trailing-slash and case differences. Without it a forged activity could name an attacker-controlled `serviceUrl`, which the plugin then uses as the base URL for outbound calls carrying the bot's token. A dedicated `api/tests/unit/test_msteams_client.py` drives the verifier with real RS256 tokens rather than patching it at the plugin boundary, covering audience, issuer, expiry and clock-skew leeway, malformed input, and the new claim binding.
- Changed: `TeamsAuthError` now derives from `ValueError`, so a rejected Azure credential reaches the Connection service's validation handler as a 400 instead of escaping as a 500 — matching every other plugin, whose credential rejection is already a plain `ValueError`. `TeamsPlatformPlugin.verify_webhook` translates it to `PermissionError`, the gateway's ingress contract, so a rejected webhook answers Microsoft with 401 instead of a 500 it would retry. The Bot Framework token cache is now keyed on a hash of the client secret alongside tenant and app id; keyed on tenant and app alone, credential validation — which runs through `acquire_token` — reported a rotated or revoked secret as valid until the cached token expired.
- Notes: Slack no longer declares `APPLICATION_PROVISIONING`. It never implemented the `build_app_package` seam, so the capability-driven download button introduced alongside the Teams package rendered on Slack Connections and failed with an unhandled `NotImplementedError`. The service now maps that seam's `NotImplementedError` to a 400 as well, so a future declare-without-implement degrades cleanly.
- Follow-up: `api/infrastructure/slack/manifest.py` is now imported only by its own tests — a remnant of the removed Slack app-creation flow, and the likely origin of the stale capability flag. Left in place; removable separately. The provider webhook route still has no integration coverage; the 401 mapping is asserted at the plugin seam only.

### 2026-08-27 — Communications on OpenClaw agents could never receive inbound messages — PR pending

- Delivered: `RUNTIME_API_URL` in the OpenClaw runtime Secret now points at port 18789, the port `openclaw gateway` actually binds, rather than 8080. The in-pod communications adapter posts inbound activities to that URL, so every inbound delivery to an OpenClaw agent failed with `ECONNREFUSED` and dead-lettered after five attempts — on Slack, Telegram and Discord as well as Teams. The pod reported healthy throughout and chat history still filled in, which is why it went unnoticed.
- Changed: The port is now a named `OPENCLAW_GATEWAY_PORT` constant in `api/domains/agents/builders/openclaw.py`. The gateway is deliberately *not* moved onto the old value: `openclaw health` resolves the default port with no override flag, so pinning the gateway elsewhere breaks the health probe and leaves agents stuck reporting "initializing". Two tests guard both halves — that the adapter targets the constant, and that `start.sh` passes no `--port`.
- Notes: Found while testing Teams end to end, but not specific to it. Recorded separately because it fixes existing platforms rather than adding Teams behaviour.

### 2026-08-27 — AF-118 — Server-side Teams app package — PR pending

- Delivered: A new `build_app_package` Platform Plugin seam, declared through the existing `APPLICATION_PROVISIONING` capability, and a Teams implementation that produces a sideloadable app package server-side. `GET /agents/{agent_id}/connections/{connection_id}/app-package` streams the zip; the schema-driven Connection panel offers a download button for any platform declaring the capability, so no platform is hard-coded in the UI. The manifest uses schema v1.17, takes publisher/website/privacy/terms values from configuration, and derives a stable manifest id from the Connection id so re-downloading updates the tenant's existing app rather than registering a second one.
- Changed: `PlatformPlugin` gained the optional `build_app_package` seam, defaulting to `NotImplementedError` like the other opt-in seams. Package generation uses only the standard library, so no dependency was added; the two required icons ship as assets under `api/domains/communications/assets/`.
- Notes: An operator can install a bot into a team or group chat only through an app package — Azure's *Open in Teams* covers personal scope alone — so this closes the last manual step that had no supported path. The package deliberately carries no credential material: the App ID it contains is public by design and appears in every Teams manifest. Publisher URLs are validated as `https` before packaging; reachability is not checked, so a misconfigured deployment pointing at an unreachable host is still rejected by Teams at upload time rather than here.
- Follow-up: The shipped icons are neutral defaults; per-Connection branding is not yet supported.

### 2026-08-26 — AF-118 — Resolve Teams channel names — PR pending

- Delivered: Teams now implements the `enrich_inbound` seam, resolving a channel's display name through the Bot Framework Teams extension (`GET {serviceUrl}/v3/teams/{teamId}/conversations`) when the inbound payload carries none. Results are cached per team, scoped by a hash of the acquired bot token so two Connections can never share a cached name — matching the existing Telegram and Discord scoping. `normalize_inbound` now records `team_id` from `channelData.team.id`, since enrichment sees envelopes rather than the provider payload.
- Changed: Nothing else. Lookup failures fall back to the envelope as normalized and never delay or reject durable acceptance, per the seam's contract. A name already present in the payload is preferred and never overwritten; direct messages skip the lookup entirely.
- Notes: This deliberately uses the **agent's own bot credentials, not Microsoft Graph** — the Teams extension requires only that the bot be installed at team scope, which it must be to receive channel messages at all. No admin consent or new permission is involved. Teams reports the default General channel with a null name so callers can localize it, and its channel id always equals the team id; that pair is labelled "General" rather than left blank.

### 2026-08-26 — AF-118 — Strip the agent's own Teams @mention — PR pending

- Delivered: Teams inbound normalization now removes the agent's own `<at>Name</at>` markup from the message text before persistence, matching Microsoft's documented guidance that the mention be stripped before the message is interpreted. Only the mention whose `mentioned.id` matches the connection's bot is removed; mentions of other people are preserved because they can be meaningful input.
- Changed: Nothing else. Slack is unaffected — its markup is `<@U123>`, an identifier rather than a display name, so it never reads as a person.
- Notes: Teams delivers channel and group-chat messages only when the agent is mentioned, so the markup was present on every one of them. Left in place it measurably degraded replies: an agent receiving `<at>Tommy</at> reply` answered "I don't see a message from Tommy to reply to", having read its own display name as a third party.

### 2026-08-26 — AF-118 — Teams round-trip fixes — PR pending

- Delivered: Teams outbound replies now send a complete Bot Framework Activity (`conversation`, `from`, `recipient`, `replyToId`) to `POST /v3/conversations/{id}/activities`. A minimal `{type, text}` body was rejected with `400 Bad Request` and dead-lettered after five attempts. `normalize_inbound` now also records the addressable Teams ids (`from_id`, `recipient_id`) in provider metadata, because `sender.id` holds the Entra object id used for policy matching and cannot address a reply. Conversations are now labelled: a named group chat uses `conversation.name`, a DM falls back to the sender's name.
- Changed: `ConversationService.list_threads` no longer uppercases the requested channel id. That was a Slack-era assumption — Slack ids are natively uppercase and Discord/Telegram ids are numeric, so uppercasing was a silent no-op for every shipped platform. Teams conversation ids are case-sensitive mixed case (`a:1mc8AgCtwYH7…`), so the lookup never matched and stored messages rendered as "No messages in this range". Exact matching is correct for all platforms; message writing already stored provider ids verbatim.
- Notes: Teams omits `channelData.channel.name` on ordinary messages — Microsoft documents it as sent only on channel modification events — so a team channel still displays its `19:…@thread.tacv2` id. Resolving it requires Microsoft Graph, which remains out of scope; DMs and named group chats are unaffected.
- Follow-up: Threaded channel replies send the raw conversation id including its `;messageid=` suffix, percent-encoded in the request path. That form has not yet been exercised against live channel traffic.

### 2026-08-26 — AF-118 — Microsoft Teams platform plugin — PR pending

- Delivered: A shipped Microsoft Teams Platform Plugin with schema-driven Azure credentials (App ID, client secret, tenant ID), the same channel/DM policy settings the other platforms expose, and a provider setup hint covering Azure Bot creation, secret retrieval, enabling the Teams channel, and pasting the Connection's webhook URL into the bot's messaging endpoint. Teams is the first plugin to use `WEBHOOK_INGRESS`: inbound activities are authenticated through `verify_webhook` against the Bot Framework JWKS, requiring the documented issuer and the Connection's own App ID as audience. Outbound replies use the Bot Connector API, threading through the reply-to-activity form.
- Changed: Nothing existing. Teams adds `skip_teams_token_validation` alongside the other per-platform validation switches and a new `api/infrastructure/msteams/` client for token acquisition, activity delivery, and inbound token verification.
- Notes: A Teams channel conversation id carries a `;messageid=` suffix on thread replies; the plugin splits it so one channel stays one conversation and the suffix becomes the thread id. Sender identity prefers the Entra `aadObjectId` and falls back to the Teams `29:` user id, because the object id is not present in every context.
- Follow-up: Teams app package (manifest) generation so operators do not hand-author a manifest to sideload the bot; no seam exists for it yet, and `APPLICATION_PROVISIONING` remains unconsumed.

### 2026-08-26 — Agent retirement releases Connection credentials — PR pending

- Delivered: Retiring (soft-deleting) an Agent now retires all owned Communication Connections in the same transaction, cancels pending and processing deliveries, clears credential identity material, and releases platform credentials for reassignment. Historical Conversation Messages remain preserved.
- Changed: Agent-owned Connection cleanup is explicit because a soft delete does not trigger the database foreign-key cascade.

### 2026-08-25 — Provider setup guidance — PR pending

- Changed: Platform descriptors now expose optional provider-owned setup hints in the schema-driven Connection form. Slack, Discord, and Telegram hints now document credential locations/formats, required scopes or Gateway intents, bot membership/visibility requirements, and provider-specific polling or privacy setup.

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
