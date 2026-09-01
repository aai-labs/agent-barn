# Communications plugins and gateway — change log

Status: Active
Epic: Communications plugin architecture
Related context: [Agents](../agents.md), [Activity and Ingest](../activity-and-ingest.md), [Runtime and Deployment](../../architecture/runtime-and-deployment.md), [gateway ownership ADR](../../adr/2026-08-22-agent-barn-owned-communications-gateway.md)

## Current state

- Delivered: Agent-subordinate Communication Connection persistence and scoped CRUD; explicit shipped Platform Plugin registry; Slack, Telegram, Discord, and Microsoft Teams plugins; the first webhook-ingress platform, authenticated by Bot Framework JWT verification at the `verify_webhook` seam; strict plugin-owned settings/credential schemas; encrypted credential envelopes; generic credential uniqueness; optimistic concurrency; platform catalogue; connection-scoped canonical Conversation Messages; durable inbound/outbound Communication Deliveries; gateway-supervised Slack Socket Mode, Telegram polling, and Discord Gateway ingress; database ingress leases; a separately served gateway; one versioned runtime-neutral protocol used by both runtimes; Slack channel/thread mention admission with durable Connection-scoped thread ownership; provider-neutral processing feedback with Slack reactions and assistant thread status; bounded adaptive idle claim backoff shared by both runtime adapters; optional, best-effort Platform Plugin name enrichment; and AF-273's content-free operational journal, typed admission dispositions, Agent-scoped diagnostics with richer aggregate health signals, filtered/chronological Journal reads including a per-Delivery lifecycle drill-down, reconnect/retry recovery controls, bounded retention, stable ordered outbound delivery, safe error projections, audit events, and low-cardinality Communications metrics.
- Changed: Agents are headless and no longer own a single Platform. Legacy provider configuration tables, DTO fields, routes, and provider-specific UI have been removed after their data is migrated into Communication Connections.
- Next: add Agent Barn Chat as another adapter at the Platform Plugin seam, then evaluate iMessage transport constraints independently of Agent runtimes.
- Blockers: none.

## Changes

### 2026-09-01 — Directory failures are reported instead of crashing — PR pending

- Fixed: A provider-side directory read that failed — a revoked token, a missing scope, a rate limit, an outage — escaped as an unhandled 500, because `SlackFetchError` is not a `ValueError`. Both the preview and saved-Connection directory endpoints now translate any provider failure through the existing error normalizer. Credential and scope problems answer 400, rate limits 429, timeouts 504, and outages 502; 401/403 are deliberately never used, since the web client treats them as its own session expiring and would sign the operator out over a bad Slack token. Provider text still never reaches the client — only the bounded summary and a validated provider code such as `missing_scope`.
- Changed: The shared error classifier now recognizes the provider error codes that carry no matching English text of their own — `missing_scope`, `not_authed`, `token_revoked`, `token_expired`, `account_inactive`, and `ratelimited` — so they land in the right category instead of Unknown.

### 2026-09-01 — Connection form reordered and directory Browse picker — PR pending

- Changed: The add-Connection form now leads with Credentials, then the Connection name, then Connection settings, so the setup guidance flows directly into the tokens it describes.
- Changed: Slack allowlists are no longer gated behind a separate workspace-validation step. Every directory-backed allowlist is an ID field again, paired with a Browse control that opens a searchable multi-select of channels, people, servers, or roles; confirming it writes only the platform IDs. Slack loads its directory from the draft credentials on first open; a saved Connection browses its own directory. Manual ID entry remains available at all times.
- Changed: Connection settings are stacked full width rather than paired into two columns, for every platform. Directory-backed fields render as one bordered token field holding its chips, a compact ID input, and the Browse control, and the picker itself has room to breathe: a padded search box separated from the list, taller rows, and the selection count in the footer.
- Fixed: Directory suggestions never appeared, and the Slack workspace-validation control could never enable, because both were keyed on snake_case plugin-schema property names. Responses are camelized in transit, so the keys are now camelCase.

### 2026-09-01 — Pre-save Slack workspace preview — PR pending

- Delivered: A user can now validate submitted Slack draft credentials and load workspace channel/user candidates before creating the Connection. The preview is Agent-update/secret-manage authorized, returns safe directory entries only, and never persists the submitted credentials or creates a Connection. Slack allowlists stay gated until that workspace load completes, with a manual-ID alternative for advanced setup.

### 2026-09-01 — Expanded Slack sample manifest — PR pending

- Changed: The UI-local Slack sample manifest now includes the requested full bot-scope and event-subscription set, including app mentions, canvases, files, pins, reactions, and membership/channel events. This is a user-provided sample manifest rather than a statement of the minimum permissions consumed by the Communications plugin.

### 2026-09-01 — Local Markdown guidance and Slack sample manifest — PR pending

- Changed: The Slack sample manifest now lives in the web application beside its copy control rather than travelling through the platform catalogue API. It is static user guidance, not a provider capability or API contract.
- Changed: Slack, Discord, Telegram, and Teams setup guidance—including Teams' post-connection instructions—is now authored in the same Markdown subset. The shared renderer adds separation before subsequent headings so multi-section instructions remain scannable.

### 2026-09-01 — Markdown setup guidance — PR pending

- Changed: Provider-owned setup hints are now authored as Markdown and the Connection form renders their headings, ordered steps, links, inline code, and emphasis as structured UI. Slack and Discord setup guidance now use this format; the Slack app-management link is directly usable instead of appearing as unstructured prose.

### 2026-09-01 — Slack manifest import instructions corrected — PR pending

- Changed: Slack setup now gives the exact manifest-import sequence—open `https://api.slack.com/apps`, New App, From Manifest, paste the copied manifest, choose the workspace and Next, then Create. The copied manifest now matches the reviewed App Home, bot display name, organization deployment, Socket Mode, event, and scope configuration.

### 2026-09-01 — Discord Connection directory discovery — PR pending

- Delivered: Discord now advertises directory discovery and lists the bot's guilds plus a selected guild's message channels, active human members, and non-default roles through credential-scoped, ten-minute cached provider reads. Member enumeration follows Discord pagination and filters bot accounts; channel choices exclude non-message channels.
- Delivered: Discord Connection editing is server-first: choose a server in the Browse server control, then select its channels, users, and roles as removable settings tokens. Raw IDs remain accepted, including for multi-server allowlists. The connection setup guidance now calls out Server Members Intent as necessary when member suggestions are used.

### 2026-09-01 — Guided Slack and Discord Connection setup — PR pending

- Delivered: Slack and Discord Connection setup hints now give ordered, provider-specific instructions instead of scope/permission inventories. The Slack flow explicitly separates manifest import, manual `xapp-` Socket Mode token creation, bot installation/token retrieval, credential entry, and channel access; Discord covers bot creation, Message Content Intent, OAuth installation permissions, token entry, and Connection policy.
- Delivered: Slack setup includes a copyable manifest and documents the manual `connections:write` app-level-token step, which manifests cannot perform.

### 2026-09-01 — Connection setup candidates and Agent platform indicators — PR pending

- Delivered: Schema-backed multi-value Connection settings now use removable value tokens. Enter commits a value, typing or pasting comma-separated values commits each complete value, and the remaining text stays editable; raw IDs remain supported for every platform.
- Delivered: Slack Connections now expose Agent-update-authorized, credential-backed directory reads for accessible channels and active users. Editing a Slack Connection offers those candidates for the channel and DM-sender allowlists while persisting only their provider IDs; the cached Slack client remains the only provider API boundary.
- Delivered: Agent list and detail reads now carry their distinct active Connection platform keys, resolved through the same accessible-Agent predicates as the Agent collection. Agent cards and headers render those platform icons without issuing one Connection query per Agent.

### 2026-08-28 — Structured safe failure diagnostics — PR pending

- Changed: Connection and Delivery failures now pass through one structured diagnostic normalizer before persistence. Recent failure details retain a safe category, operation, HTTP status, provider error code, retryability, bounded retry-after value, and provider request ID without storing provider URLs, credentials, headers, bodies, or exception text. Legacy error projections remain redacted when no validated diagnostic envelope exists.
- Changed: The Connection details page's expanded Recent failure cards and Delivery transition details render the structured diagnostics, giving authorized Agent users actionable provider context while keeping the content-free journal boundary intact.

### 2026-08-28 — AF-273 — Journal filters, delivery lifecycle drill-down, and richer summary signals — PR pending

- Delivered: `GET .../journal` now accepts server-backed `since`/`until`, `stage`, `failed_only`, `retryable_only`, `direction`, and `delivery_id` filters, composed as SQL predicates in `CommunicationOperationalRepository.find_journal_page` against the existing Delivery join — routes and the service stay thin, and authorization is unchanged. `retryable_only` reads the live joined Delivery status rather than the historical Journal stage, so a Delivery Transition that has already been retried drops off the filter even though its `dead_lettered` entry remains in the Journal. The same endpoint now accepts `order=asc`, which combined with `delivery_id` serves one Delivery's complete lifecycle in chronological order — a read, not a new table. The Connection details page's transition rows link to this as "View delivery timeline".
- Delivered: The summary endpoint reports last successful provider connection, current error age, consecutive failure count, delivery success rate, and oldest pending Delivery age. The first three are deliberately unbounded by the diagnostics window — they answer "what is this Connection's current trajectory," not "what happened in the selected window" — while delivery success rate reuses the already-windowed delivery counts.
- Changed: Diagnostics now returns a server-grouped Connection health read model made from actual provider health transitions. It carries a windowed state timeline plus recent connection incidents, reconnect count, median connect time, longest outage, recovery outcomes, and safe causes; provider observation and policy-admission rows remain available only in the raw Journal because they are not connectivity states. The summary and Journal accept the same inclusive, maximum-90-day window contract.
- Changed: The Connection activity table gained a filter bar (time range, stage, direction, delivery ID, failed/retryable toggles) and a "Health signals" summary row. Journal stage/status text is now lowercased consistently before CSS capitalization, matching the existing stage-label convention instead of leaking raw uppercase enum values into the DOM.

### 2026-08-28 — AF-273 — Connection details page — PR pending

- Changed: Messaging settings now show each Connection's current observed status and compact actions. A dedicated Connection details page holds summary diagnostics, recovery controls, and a paginated Delivery transitions explorer. Summary diagnostics include capped safe recent failures and grouped provider-state history; Delivery transitions remain backed by the Journal endpoint. Failure cards expand to show safe error metadata, occurrence times, and associated Delivery IDs; eligible delivery retries remain available from the Delivery lifecycle. The compact view offers a manual status refresh; it reads the most recently recorded supervisor state and does not create a provider probe.
- Changed: Journal reads enrich Delivery Transitions from their linked live Delivery with direction and current status. The explorer presents inbound/outbound and status badges plus per-entry duration without storing duplicate or content-bearing facts in the append-only Journal, and does not expose provider error details for copying.
- Changed: Connection details now leads with an incident-oriented Connection health view—a state timeline, reconnect/connect/outage summary, and Recent incidents table—and keeps Delivery transitions as the primary activity table. Recent failures explain safe error details inline through collapsible cards; the raw connection-level Journal remains an API troubleshooting source rather than a page-level table. One diagnostics window drives the windowed cards and Delivery transitions; current provider state and freshness remain explicitly separate from that window.

### 2026-08-27 — AF-273 — Communication diagnostics and recovery controls — PR pending

- Delivered: An append-only, content-free Connection operation journal records provider observation, policy admission, delivery stages, connection health transitions, attempts, durations, bounded error metadata, dead-lettering, reconnect requests, retries, and successful delivery recovery. Slack, Telegram, Discord, and Teams now return typed admission dispositions (`accepted`, `bot_ignored`, `event_ignored`, `mention_required`, `user_denied`, `channel_denied`, and `malformed_payload`); only accepted envelopes create inbound Deliveries, while rejected admissions use a distinct `policy_rejected` journal stage. Provider observation and policy journal writes are best-effort: diagnostics persistence failures are logged but must not drop a consumed polling event or reject ingress.
- Delivered: Agent-scoped diagnostics expose provider connectivity separately from end-to-end delivery health, pipeline and delivery counts, current queue depth/oldest queued age, latency summaries, capped recent failures, and the latest 50 transitions without message content or credentials. Authorized users can request one Connection reconnect or retry one active dead-lettered outbound Delivery while preserving its message and idempotency identity. Outbound claims preserve ordering within a conversation, and provider adapters receive a stable opaque idempotency key on every retry; error summaries are allowlisted/redacted on both writes and reads, while the supervisor prunes rows outside the configured retention window.
- Changed: Connection health changes, dead-lettered Deliveries, requested retries, and successful recovery are registered as typed Organization-scoped Domain Events and projected through the existing Security Audit handler. Communications metrics expose status, outcomes, queue age/depth, latency, reconnects, and policy dispositions with no Organization, Agent, Connection, Conversation, or User labels.
- Changed: Delivery transition detail derives queue wait, processing time, and any scheduled retry from the live Delivery; raw payloads, provider identifiers, and identities remain excluded. Ordinary successful Connection events are compact rows, while failures, degraded state, and reconnect requests retain a focused drill-down.
- Follow-up: No bulk replay, org-wide dashboard, alert routing, or provider-specific recovery buttons were added.

### 2026-08-28 — AF-118 — Harden the Teams authentication path — PR pending

- Delivered: Inbound Bot Framework tokens are now bound to the activity they arrive with. `verify_inbound_jwt` requires the `serviceurl` claim and matches it against the activity's `serviceUrl`, ignoring trailing-slash and case differences. Without it a forged activity could name an attacker-controlled `serviceUrl`, which the plugin then uses as the base URL for outbound calls carrying the bot's token. A dedicated `api/tests/unit/test_msteams_client.py` drives the verifier with real RS256 tokens rather than patching it at the plugin boundary, covering audience, issuer, expiry and clock-skew leeway, malformed input, and the new claim binding.
- Changed: `TeamsAuthError` now derives from `ValueError`, so a rejected Azure credential reaches the Connection service's validation handler as a 400 instead of escaping as a 500 — matching every other plugin, whose credential rejection is already a plain `ValueError`. `TeamsPlatformPlugin.verify_webhook` translates it to `PermissionError`, the gateway's ingress contract, so a rejected webhook answers Microsoft with 401 instead of a 500 it would retry. The Bot Framework token cache is now keyed on a hash of the client secret alongside tenant and app id; keyed on tenant and app alone, credential validation — which runs through `acquire_token` — reported a rotated or revoked secret as valid until the cached token expired.
- Notes: Slack no longer declares `APPLICATION_PROVISIONING`. It never implemented the `build_app_package` seam, so the capability-driven download button introduced alongside the Teams package rendered on Slack Connections and failed with an unhandled `NotImplementedError`. The service now maps that seam's `NotImplementedError` to a 400 as well, so a future declare-without-implement degrades cleanly.
- Follow-up: The provider webhook route still has no integration coverage; the 401 mapping is asserted at the plugin seam only.

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
