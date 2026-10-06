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
  - **What it sends:** one `/batch/` per event. The capture has `uuid` = `event_id` and `timestamp` = `occurred_at`. Each worker process names the installation group once, with a `$groupidentify` (deterministic `uuid5`) in its first successful batch, and again only if the name changes.
  - **Who it's attributed to:** `distinct_id` is the acting user's UUID. A member who removed themselves resolves through `payload.user_id`.
  - **Properties:** allowlisted fields only. `agent.updated` sends changed field names but never their values. Every event also gets `source`, `$geoip_disable`, `$lib`, and the installation and organization groups.
  - **User details:** `$set` email and name are added only when `ANALYTICS_INCLUDE_USER_DETAILS` is true.
  - **Skipped silently:** analytics disabled, non-human actors, and actors that can't be resolved.
  - **When PostHog fails:** an unreachable PostHog is retried on attempts 1 and 2, then dropped with a warning on attempt 3. A rejected batch dead-letters.
- Also delivered: the nine slice-1 events now list `product_analytics.posthog` alongside their existing handlers. The behaviour contract is [`../product-analytics.md`](../product-analytics.md).
- Also delivered: deployment wiring.
  - The API chart renders `ANALYTICS_ENABLED`, which defaults to false in the chart and the Helmfile, and `ANALYTICS_INCLUDE_USER_DETAILS`. It renders `INSTALLATION_NAME` only when set.
  - `deploy.yml` enables analytics and user details on `main` only, so staging is off. `deploy-public.yml` enables both.
  - `.env.deploy.spec` ships analytics off, and `release-bundle.yml` turns it on in customer bundles.
  - The opt-out is documented in `operations.md` and the README.
- Also delivered: local end-to-end verification against a recording stub (see the 2026-10-06 entry). A one-off check against the real project from a local stack, labelled `local-dev-test` at the user's request, showed the events arriving in Live Events.
- In transition: nothing in code. Analytics starts sending on the next `main` deploy, the next public release, and the next customer bundle.
- Next: the production confirmation after release. Then the follow-up slices: Domain Events for organization created, signup/login, and Conversation Messages.
- Blockers: the Group Analytics add-on must be enabled on the Agent Barn PostHog project before the production confirmation.

## Changes

### 2026-10-06 — AF-357 — Analytics off by default in Helm; installation named once per process

- Delivered:
  - **Default off.** A Helm or Helmfile install sends nothing unless `ANALYTICS_ENABLED` is set to true. Release bundles, `main`, and public deploys still set it.
  - **Group identify once.** The installation `$groupidentify` is sent once per worker process, or when the name changes, instead of with every event. The local E2E showed it doubling every row in Live Events.
- Changed: `helm/agentbarn-api/values.yaml`, `helmfile.yaml.gotmpl`, `api/domains/analytics/event_handlers.py` (now `@singleton`), `operations.md`, `README.md`, `product-analytics.md`.
- Verified:
  - The render check passes, and `helmfile template` gives unset → false, true → true, false → false. `helm lint` is clean.
  - The handler tests pass: the second event omits `$groupidentify`, a failed send keeps it pending, and redelivery keeps the capture ids.
- Follow-up: the production confirmation.

### 2026-10-06 — AF-357 — Local end-to-end verification

- Observed on local k3d (image from this branch, migration `5a1e7c3b9d20`). The API and worker were pointed at a recording PostHog stub with `ANALYTICS_POSTHOG_HOST=http://host.docker.internal:8765`, so nothing reached the real project. Email was disabled for the run.
- **Real API actions:**
  - agent create, rename, start, stop, delete
  - member add, role change, removal
  - an admin removing themselves
  - ownership transfer
- **Delivery and payload checks:**
  - Every one of 13 `product_analytics.posthog` deliveries succeeded on attempt 1.
  - The stub received exactly 13 batches. Each held the capture and the installation `$groupidentify`.
  - In each batch, `api_key` was the default token, `uuid` matched the event id, and `timestamp` matched the event time. `distinct_id` was the acting user, and the leaver for self-removal.
  - The installation and organization groups were correct, and only allowlisted fields were sent.
  - No agent name, email, or display text appeared.
- **User details:** with `ANALYTICS_INCLUDE_USER_DETAILS=true`, `$set` carried the email and name.
- **Redelivery:** a delivery reset to PENDING and re-enqueued through Redis resent an identical `uuid`, `timestamp`, and `distinct_id` (attempt 2, SUCCEEDED).
- **Opt-out:** with `ANALYTICS_ENABLED=false`, the delivery succeeded and the stub received 0 requests.
- **Outage:** with the stub answering 503, attempts 1 and 2 retried, attempt 3 logged "Product analytics dropped", and the delivery SUCCEEDED rather than dead-lettering. `phc_` did not appear in the API or worker logs.
- **Finding:** the PR 8 chart default (`analyticsEnabled: true`) turned analytics on in a developer's local deploy. It was caught before any event was sent (0 deliveries). The fix is the next slice.

### 2026-10-06 — AF-357 — Deployment wiring

- Delivered: the analytics switches reach every API process through the chart Secret. They are on for Helm installs, our `main` deploy, and public releases, and off for staging and developer deploys.
- Changed: `helm/agentbarn-api/values.yaml`, `templates/secret.yaml`, `helmfile.yaml.gotmpl`, `.env.deploy.spec`, `.env.spec`, `.github/workflows/deploy.yml`, `deploy-public.yml`, `release-bundle.yml`, `docs/guidelines/operations.md`, `README.md`, `product-analytics.md`.
- Verified:
  - `helm template` and `helmfile template` render `"true"`/`"false"` and the optional name as expected for unset, opt-out and override values.
  - The release-bundle `sed` turns the spec's `false` into `true`.
  - `helm lint` is clean.
- Follow-up: the local end-to-end check and the production confirmation.

### 2026-10-06 — AF-357 — Subscribe the slice-1 events

- Delivered: the slice-1 events produce a `product_analytics.posthog` delivery.
  - Agent events: `agent.created`, `agent.updated`, `agent.started`, `agent.stopped`, `agent.deleted`.
  - Organization events: `organization.member.added`, `organization.member.removed`, `organization.role.changed`, `organization.ownership_transferred`.
  - `agent.created` previously had no handler. The monitor's handler-less example is now `agent.restore_point.created`.
- Changed: `api/domains/events/catalog.py`. Tests that pinned handler lists, or assumed a single delivery per event, now expect the new handler or select by handler name. These are in `test_outbox_messages.py`, `test_event_delivery_monitor.py`, `test_agent_lifecycle_email_handler.py`, `test_agents.py`, `test_organization_members.py`, and `test_event_handler_registry_wiring.py`.
- Docs: new [`product-analytics.md`](../product-analytics.md); updated `domain-events.md`, `CONTEXT.md` (Installation), `system-map.md`, `api.md`, and `INDEX.md`.
- Follow-up: the deployment wiring slice.

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
