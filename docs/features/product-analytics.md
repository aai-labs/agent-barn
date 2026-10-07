# Product analytics

## Read when

Read this before you change which business events reach PostHog, what they carry, how users and Installations are identified, or how analytics is switched on.

## Role in the system

Product analytics forwards selected Domain Events to PostHog, in the Agent Barn project shared with the agentbarn.dev website. It is a Domain Event consumer: the `product_analytics.posthog` Event Handler receives committed events through the outbox. Services contain no analytics calls. Every Agent Barn Installation reports, including customer self-hosted ones, and each one can be told apart.

## Invariants

- **On switch.** Analytics is off unless `ANALYTICS_ENABLED` is true and a project token is set. A blank `ANALYTICS_ENABLED` counts as off. When it is off, the handler completes every delivery without sending anything. Helm installs default it to off; release bundles and AAI Labs production deploys turn it on. Per-deployment defaults and the opt-out are in [`../guidelines/operations.md`](../guidelines/operations.md#product-analytics).
- **Who an event is attributed to.**
  - Only events with a human actor (Membership or User) are sent. System and Runtime actors are skipped.
  - `distinct_id` is the acting user's UUID.
  - A Membership actor is resolved only within the event's Organization.
  - A member who removed themselves is attributed through the event's `user_id`.
  - An actor that can no longer be resolved is skipped and logged.
- **What an event carries.**
  - Only allowlisted identifiers and safe fields (see [Events](#events)).
  - Names, display snapshots, and changed values are never sent.
  - User email and name are sent as person properties only when `ANALYTICS_INCLUDE_USER_DETAILS` is true.
- **Groups.** Every event belongs to the `installation` group, keyed by the Installation id. It is named from `INSTALLATION_NAME`, or the `WEB_APP_URL` host when that is unset.
  - Organization-scoped events also belong to the `organization` group, keyed by the Organization id, and carry `organization_id`.
  - Platform-scoped events (`organization_id` is null) carry neither. They are sent only for a User Actor, because a Membership Actor cannot be resolved without an Organization.
- **Labels and privacy flags.** Every event carries `source: agentbarn-api` and `$lib: agentbarn-api`, so app events can be separated from website events. It also carries `$geoip_disable: true`.
- **Redelivery.** A redelivered event sends the same capture ids: the capture's `uuid` is the `event_id` and its timestamp is `occurred_at`. PostHog de-duplicates matching events eventually, not immediately.
- **Installation naming.** Each worker process names the Installation group once, with a `$groupidentify` in the first batch it sends successfully. It names it again only if the name changes. A failed or dropped send does not count, so the next batch retries the naming.
- **Failure handling.**
  - An unreachable PostHog (transport error, 408, 429 or 5xx) is retried on delivery attempts 1 and 2, then dropped with a warning on attempt 3.
  - Any other rejection dead-letters the delivery.
- **No backfill.** Events committed before the handler was attached never reach PostHog.

## Data flow

1. A business mutation commits its Domain Event together with one Event Delivery per intended handler.
2. The worker claims the `product_analytics.posthog` delivery.
3. The handler resolves the actor to a user and builds one `/batch/` request. The request holds the event capture, plus a `$groupidentify` naming the Installation group when this process has not named it yet.
4. `PostHogClient` posts the batch to `{ANALYTICS_POSTHOG_HOST}/batch/` with a 5-second limit.

## Events

| Event | Properties beyond the common set |
| --- | --- |
| `agent.created`, `agent.deleted` | `agent_id`, `runtime` |
| `agent.started`, `agent.stopped` | `agent_id`, `runtime`, `previous_status`, `new_status` |
| `agent.updated` | `agent_id`, `changed_fields` (field names only) |
| `organization.member.added`, `organization.member.removed` | `membership_id`, `role` |
| `organization.role.changed` | `membership_id`, `previous_role`, `new_role` |
| `organization.ownership_transferred` | `previous_owner_membership_id`, `new_owner_membership_id` |
| `organization.created` | none (the creator is the person; for `POST /platform/users`, the Platform Administrator) |

The common set is `source`, `installation_id`, `$groups`, `$geoip_disable`, and `$lib`. Organization-scoped events add `organization_id`. When user details are enabled, `$set` (email and name) is added.

## Installation

An Installation is one Agent Barn database. The `installation` table holds one generated id, seeded by migration `5a1e7c3b9d20`. `InstallationRepository.get_id()` recreates the row if a restore or truncation removed it. A database cloned from another Installation carries that Installation's id.

## Project token

The default `ANALYTICS_POSTHOG_PROJECT_TOKEN` is the Agent Barn PostHog project token, committed in `api/core/config.py`. This is an approved exception to the repository rule against committing tokens. PostHog project tokens (`phc_`) are write-only and public by design: "It is ok for your project token (starts with phc_) to be public." The agentbarn.dev website ships the same token. Personal API keys (`phx_`) must never be committed.

## Privacy

Deleting a user in Agent Barn does not erase their PostHog person. With user details disabled, the person record holds only the user UUID.

## Source map

| Concern | Authoritative source |
| --- | --- |
| Event Handler, allowlist, and actor resolution | `../../api/domains/analytics/event_handlers.py` |
| Installation model and repository | `../../api/domains/analytics/models.py`, `../../api/domains/analytics/repository.py` |
| PostHog batch client | `../../api/infrastructure/posthog/` |
| Configuration | `../../api/core/config.py` |
| Event subscription | `../../api/domains/events/catalog.py` |
| Tests | `../../api/tests/integration/test_product_analytics_handler.py`, `../../api/tests/unit/test_posthog_client.py`, `../../api/tests/unit/test_config_analytics.py`, `../../api/tests/unit/test_event_handler_registry_wiring.py` |
| Delivery state | [`product-analytics/CHANGELOG.md`](product-analytics/CHANGELOG.md) |

## Change impact

Adding an event requires its name in the handler's allowlist and in the event's `handler_names`. It also needs a reviewed property list and handler tests. Adding a property requires confirming that it holds no names, display text, secrets, or user content. Changing identity, groups, or the person properties changes historical PostHog data, so record it in this document.
