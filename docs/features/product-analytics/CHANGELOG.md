# Product analytics — change log

Status: Active
Epic: AF-357 — PostHog business events
Related context: [Domain Events](../domain-events.md), [Identity and Organizations](../identity-and-organizations.md), [Agents](../agents.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: this change log, and the Installation identity. The `installation` table (migration `5a1e7c3b9d20`) holds one generated id, and `InstallationRepository.get_id()` in `api/domains/analytics/` returns it. If the row is missing, `get_id()` recreates it.
- Also delivered: the analytics configuration in `api/core/config.py`.
  - `ANALYTICS_ENABLED` is off by default. A blank value counts as off.
  - `ANALYTICS_INCLUDE_USER_DETAILS` controls whether user email and name are sent.
  - `ANALYTICS_POSTHOG_HOST` defaults to PostHog Cloud EU.
  - `ANALYTICS_POSTHOG_PROJECT_TOKEN` defaults to the Agent Barn project token. Committing it is an approved exception to the AGENTS.md token rule, because PostHog project tokens are public by design.
  - `INSTALLATION_NAME` falls back to the `WEB_APP_URL` host.
- Also delivered: `PostHogClient.send_batch` in `api/infrastructure/posthog/`.
  - Makes one POST to `{host}/batch/` and waits at most 5 seconds.
  - A 408, a 429, a 5xx or a transport failure raises `RetryablePostHogException`. Any other non-200 status raises `TerminalPostHogException`.
  - Never logs the token.
- Also delivered: test safety. The test suite forces `ANALYTICS_ENABLED=false`, and an autouse guard blocks any call to a `posthog.com` URL. `MockPostHogModule` is a recording fake for handler tests.
- Also delivered: `OrganizationUserRepository.get_member_with_user_by_membership_id(membership_id, organization_id)`. It resolves a Membership Actor to its user, and only within the given Organization.
- Also delivered: `ProductAnalyticsHandler` (`product_analytics.posthog`) in `api/domains/analytics/event_handlers.py`, registered in `provide_event_handler_registry`.
  - **What it sends:** one `/batch/` per event. The capture has `uuid` = `event_id` and `timestamp` = `occurred_at`. A `$groupidentify` names the installation group (deterministic `uuid5`).
  - **Who it's attributed to:** `distinct_id` is the acting user's UUID. A member who removed themselves resolves through `payload.user_id`.
  - **Properties:** allowlisted fields only. `agent.updated` sends changed field names but never their values. Every event also gets `source`, `$geoip_disable`, `$lib`, and the installation and organization groups.
  - **User details:** `$set` email and name are added only when `ANALYTICS_INCLUDE_USER_DETAILS` is true.
  - **Skipped silently:** analytics disabled, non-human actors, and actors that can't be resolved.
  - **When PostHog fails:** an unreachable PostHog is retried on attempts 1 and 2, then dropped with a warning on attempt 3. A rejected batch dead-letters.
- In transition: the handler is registered but no catalogue event lists it yet, so it receives no deliveries.
- Next: subscribe the nine slice-1 events in `catalog.py` and update the tests that pin handler lists.
- Blockers: the Group Analytics add-on must be enabled on the Agent Barn PostHog project before the production confirmation.

## Changes

### 2026-10-06 — AF-357 — Product analytics Event Handler

- Delivered: the handler and its registration. Nothing is sent yet, because no event subscribes it.
- Changed: `api/domains/analytics/event_handlers.py`, `PRODUCT_ANALYTICS_HANDLER` in `api/domains/events/catalog.py`, `api/infrastructure/app.py`.
- Follow-up: the event subscription slice.

### 2026-10-06 — AF-357 — Org-scoped membership lookup

- Delivered: membership-to-user resolution scoped to one Organization. A membership from another Organization, or one that no longer exists, resolves to nothing.
- Changed: `api/domains/users/organization_users/repository.py`.
- Follow-up: the Event Handler slice.

### 2026-10-06 — AF-357 — PostHog client

- Delivered: the batch client with retryable or terminal failure classes, and the test guard and fake.
- Changed: `api/infrastructure/posthog/`, `api/tests/conftest.py`, `api/tests/mocks/posthog.py`.
- Follow-up: the org-scoped membership lookup slice.

### 2026-10-06 — AF-357 — Analytics configuration

- Delivered: the analytics switches, the PostHog host and token defaults, and the installation display name. Analytics stays off unless `ANALYTICS_ENABLED` is true and a token is set.
- Changed: `api/core/config.py`.
- Follow-up: the PostHog client slice.

### 2026-10-06 — AF-357 — Installation identity

- Delivered: one Installation id per database. The migration seeds it; the repository recreates it after a restore or truncation and caches it per process.
- Changed: schema (`installation` table, migration `5a1e7c3b9d20`), new `api/domains/analytics/` domain, `api/migrations/env.py` model import.
- Follow-up: the analytics configuration slice.

### 2026-10-06 — AF-357 — Epic change log

- Delivered: the epic change log, routed from `docs/INDEX.md`.
- Changed: docs only.
- Follow-up: the Installation identity slice.
