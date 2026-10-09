# Product analytics — change log

Status: Active
Epic: AF-357 — PostHog business events
Related context: [Domain Events](../domain-events.md), [Identity and Organizations](../identity-and-organizations.md), [Agents](../agents.md), [epic guideline](../../guidelines/epics.md)

## Current state

- Delivered: this change log, and the Installation identity. The `installation` table (migration `5a1e7c3b9d20`) holds one generated id, and `InstallationRepository.get_id()` in `api/domains/analytics/` returns it. If the row is missing, `get_id()` recreates it.
- Also delivered: the analytics configuration in `api/core/config.py`.
  - `ANALYTICS_ENABLED` is on by default. Explicit false opts out; a blank value counts as off in Config.
  - User-detail collection and its setting have been removed. User email and full name are never sent; UUID attribution remains.
  - `ANALYTICS_POSTHOG_HOST` defaults to PostHog Cloud EU.
  - `ANALYTICS_POSTHOG_PROJECT_TOKEN` defaults to the Agent Barn project token. Committing it is an approved exception to the AGENTS.md token rule, because PostHog project tokens are public by design.
  - The Installation label is the normalized `WEB_APP_URL` hostname for remote installs, or `local-<first 8 UUID characters>` for local hosts. Events carry `installation_environment`; the persisted UUID remains the identity. There is no configurable name override.
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
  - **User privacy:** human actor captures contain no email or full name and no user `$set` properties.
  - **Skipped silently:** analytics disabled, non-human actors, and actors that can't be resolved.
  - **When PostHog fails:** an unreachable PostHog is retried on attempts 1 and 2, then dropped with a warning on attempt 3. A rejected batch dead-letters.
- Also delivered: the nine slice-1 events now list `product_analytics.posthog` alongside their existing handlers. The behaviour contract is [`../product-analytics.md`](../product-analytics.md).
- Also delivered: deployment wiring.
  - The API chart renders `ANALYTICS_ENABLED`, which defaults to true in the chart and the Helmfile, with no user-details setting. The Installation label is derived from `WEB_APP_URL`.
  - `deploy.yml` enables analytics on `main` only, so staging sends nothing by default. `deploy-public.yml` enables analytics. Neither workflow configures user-detail collection.
  - `.env.deploy.spec` and customer release bundles ship analytics on. The local `.env.spec` explicitly disables it.
  - The opt-out is documented in `operations.md` and the README.
- Also delivered: local end-to-end verification against a recording stub (see the 2026-10-06 entry). A one-off check against the real project from a local stack, labelled `local-dev-test` at the user's request, showed the events arriving in Live Events.
- In transition: nothing in code. Analytics starts sending on the next `main` deploy, the next public release, and the next customer bundle.
- Also delivered: the handler supports platform-scoped events (installation group only).
- Also delivered: `organization.created`, `organization.updated`, `organization.deleted`, `user.logged_in`, `user.signed_up`.
- Also delivered: hourly message counts (CronJob).
- Next: local E2E of the new events and the CronJob against the fake PostHog, then the production confirmation after release.
- Blockers: the Group Analytics add-on must be enabled on the Agent Barn PostHog project before the production confirmation.

## Changes

### 2026-10-09 — AF-357 — Integrate remote naming changes

- Merged the remote hostname normalization and local/remote event properties while preserving removal of user-detail collection, synchronized naming, and the domain-change identity regression.
- Local/remote classification is descriptive; `ANALYTICS_ENABLED` controls sending. Developer stacks using custom domains may be labelled remote.
- Verified: 83 focused analytics tests pass; API static checks and migration-head validation pass.

### 2026-10-09 — AF-357 — Only developer machines count as local

- Delivered: following an independent audit, `installation_environment = local` now means an empty host, `localhost`, `*.localhost`, or a loopback or unspecified IP (including IPv4-mapped IPv6).
  - `*.local` hosts, private, link-local and CGNAT IPs, and dotless intranet names are now `remote` and named by their host.
  - The reason: the customer template ships `WEB_APP_URL=http://agentbarn.local`, and on-premises installs often use private IPs. Under the previous rule, both were hidden by the `remote` filter.
- Fixed: a malformed `WEB_APP_URL` such as `http://[abc` made `urlparse` raise inside every analytics send. It now gives an empty host and counts as local.
- Also fixed: a URL without a scheme now yields its host instead of nothing, and a trailing dot is stripped, so `app.example.com.` and `app.example.com` share one name.
- Changed: `core/config.py` (`web_app_host`, `is_local_installation`), `product-analytics.md`, `operations.md`, and this file's Current state, which still described `INSTALLATION_NAME`.
- Verified:
  - The config unit tests cover:
    - 14 local URLs
    - 10 remote URLs
    - 5 host normalisation cases, including credentials that never reach the name and the malformed URL
  - 10 of them failed before the change, including the `Invalid IPv6 URL` crash.
  - The config, handler and message-count suites pass (66).
- Follow-up: the local end-to-end run, which also covers `agentbarn.local`, a private IP and a malformed URL.

### 2026-10-09 — AF-357 — Installation name from the domain, plus installation_environment

- Delivered: following team feedback, the Installation is named from `WEB_APP_URL` with no configuration. Every event, including message counts, also carries `installation_environment`.
  - remote: the lowercased host
  - local (empty, `localhost`, `*.localhost`, `*.local`, or a loopback, private or link-local IP): `local-<first 8 of the Installation id>`
  - The `$groupidentify` name matches.
  - `installation_environment = remote` filters out every developer stack.
  - The `INSTALLATION_NAME` variable is removed everywhere, and a leftover one is ignored.
- Changed: `core/config.py` (`web_app_host`, `is_local_installation`; removed `installation_name` and `installation_display_name`), `analytics/event_handlers.py` (`installation_name()`, `installation_environment()`), `analytics/message_counts.py`, the Helm values and Secret, Helmfile, `.env.spec`, `.env.deploy.spec`, `deploy.yml` and `deploy-public.yml` (the PR 16 names removed), `product-analytics.md`, `operations.md`, `README.md`.
- Verified:
  - The config, handler and message-count tests pass:
    - local and remote hosts
    - host normalisation
    - a leftover variable is ignored
    - remote and local naming, and the group name
  - They failed before the change.
  - The analytics suites pass (76).
  - Render check 18 of 18: the Secret, Helmfile, specs and workflows carry no `INSTALLATION_NAME`. `helm lint` is clean, and the workflows parse.
- Follow-up: local end-to-end check.


### 2026-10-09 — AF-357 — Remove user-detail collection

- Delivered: analytics no longer sends user email or full name. Human actor attribution stays UUID-based; existing user-detail environment entries have no effect in updated processes.
- Removed: the user-details configuration field and validator input, person-property sending branch, workflow overrides, Helm value and Secret entry, Helmfile wiring, and environment-spec suggestions. Installation count pseudo-person metadata remains content-free.
- Changed: configuration, analytics handler, privacy regression tests, deployment wiring, README, operations guidance, and the analytics feature contract.
- Verified before the removal: the legacy-setting regression failed with the old setting set to true because the capture contained user email and full name.
- Verified after removal: all 60 focused configuration, handler, count, and wiring tests pass, including legacy-setting privacy regressions. Static checks, the migration-head check, whitespace checks, and deployment workflow/chart YAML parsing pass. Helm render checks remain unavailable because Helm is not installed.
- Historical data: this change does not remove names or emails previously sent to PostHog.

### 2026-10-09 — AF-357 — Derive Installation labels from the app URL

- Delivered: Installation labels come from the `WEB_APP_URL` hostname, or the persisted UUID when no hostname is available. The label excludes URL credentials, port, path, query, and fragment. Changing the hostname renames the PostHog group while preserving its UUID key.
- Removed: the `INSTALLATION_NAME` setting, Helm value, Secret entry, workflow overrides, and environment-spec suggestions. Business and hourly count events keep their `installation_name` property.
- Changed: configuration, analytics naming synchronization, tests, Helm/Helmfile and deployment wiring, README, operations guidance, and the analytics feature contract.
- Verified: 64 focused configuration, handler, count, identity, and wiring tests pass. Static checks, the single migration-head check, and whitespace checks pass. Deployment workflows and chart values parse as YAML with no name override; Helm render checks could not run because Helm is unavailable.

### 2026-10-09 — AF-357 — installation_name on every event

- Delivered: every captured event, including hourly message counts, carries `installation_name`.
  - It is `INSTALLATION_NAME`, else the `WEB_APP_URL` host, else the Installation id, so it is never empty.
  - The installation group's `$group_set.name` uses the same value.
  - PostHog can filter and break down by Installation through this event property, without Group Analytics.
  - Our deploys are named explicitly: `production` (k3s `main`), `staging` (k3s `staging`) and `cloud` (public).
- Changed: `analytics/event_handlers.py` (the `installation_name()` helper), `analytics/message_counts.py`, `.github/workflows/deploy.yml`, `.github/workflows/deploy-public.yml`, `product-analytics.md`, `operations.md`.
- Verified:
  - The handler and message-count tests expect `installation_name`, including platform events and the fallback to the Installation id when no name is configured. They failed before the change.
  - The handler, message-count, wiring, config, and org-event suites pass.
  - Both workflows parse, and `helmfile template` renders `INSTALLATION_NAME` as `production`, `staging` and `cloud` into the API Secret.
- Note: events already in PostHog have no `installation_name`. It applies to events sent after deployment.

### 2026-10-09 — AF-357 — Synchronize Installation naming

- Delivered: a per-handler lock protects the Installation naming check, batch send, and success update. Concurrent first deliveries send one group-identification capture; captures after successful naming can still send concurrently. Failed sends leave naming eligible for the next delivery.
- Changed: the analytics handler, concurrent regression coverage, and the product analytics contract.
- Verified before the fix: the concurrent regression failed at the naming-count assertion (expected one, received two), while both business captures were recorded.
- Verified after the fix: all 73 focused analytics tests pass, including the concurrent regression and retry-after-failure coverage. Inverting the naming condition makes the concurrent test fail. `make check-api check-migrations` and diff whitespace checks pass.

### 2026-10-09 — AF-357 — Enable analytics by default

- Delivered: Config, Helm, Helmfile, and the deployment environment spec default analytics to on. Explicit false still opts out. Staging, tests, and the local development environment spec explicitly disable it.
- Privacy: user email and name remain off by default through `ANALYTICS_INCLUDE_USER_DETAILS`. Production and staging workflows explicitly enable user details; staging analytics remains disabled. The deployment spec documents the privacy default.
- Changed: analytics configuration and default/opt-out tests, deployment defaults, README, operations guidance, and the analytics feature contract.
- Verified: 55 focused configuration, client, handler, and message-count tests pass; `make check-api check-migrations` and diff whitespace checks pass. Helm render checks were not rerun because Helm is unavailable in this environment.

### 2026-10-07 — AF-357 — organization.updated uses a User actor

- Delivered: `organization.updated` now carries a User actor (the acting user) instead of a Membership actor. It still reaches PostHog when the Organization, and with it the Membership, is deleted before the worker delivers it. This fixes the E2E finding. `organization.model_allowlist.changed` keeps its Membership actor for the security audit.
- Changed: `organizations/service.py` (the `organization.updated` actor only), `test_organization_updated_event.py`, `domain-events.md`.
- Verified:
  - The new regression test (rename, delete, then process the delivery) sends as the owner with the organization group. It failed before the fix.
  - The actor assertion is now USER, and the allowlist event still has a MEMBERSHIP actor.
  - `test_organization_update_models`, `test_organization_updated_event` and the wiring test pass (28).
- Remaining by design: other Membership-actor events (agent and member events) are still skipped if the actor's Membership is gone before delivery (skip-and-log).

### 2026-10-07 — AF-357 — Local end-to-end verification of the new events and message counts

- Observed on local k3d (image from this branch, migration `6c3f9a2e8b41`, chart default `ANALYTICS_ENABLED=false`).
  - The api and worker were pointed at a recording stub with `ANALYTICS_POSTHOG_HOST=http://host.docker.internal:8765` and email was disabled. Nothing reached the real project.
  - The overrides were removed afterwards, and analytics is off again by default.
- **Real API flows:**
  - `POST /platform/users` → `organization.created` (actor: admin)
  - `/auth/set-password` → `user.signed_up`; a reused token → 400 and no event
  - logins → `user.logged_in`; a failed login and `/auth/refresh` → no event
  - `POST /organizations` → `organization.created`
  - PATCH rename → `organization.updated` with `["name"]`; the same name again → no event
  - DELETE → `organization.deleted`
- **Deliveries:** every one of the 9 deliveries SUCCEEDED on attempt 1.
- **Stub:** 8 captures matched the database rows by uuid, timestamp, person, groups and fields.
  - Platform events had only the installation group.
  - No email addresses appeared.
  - Exactly one `$groupidentify` across all batches, which confirms once-per-process naming.
- **Message counts:** seeded web 2 inbound, 1 outbound and telegram 1 inbound in 07:00 UTC, plus one in the next hour. `main()` ran in the worker pod twice.
  - The counts were exact (2/1/1), and the next-hour message was excluded.
  - Three distinct uuids, identical on the re-run, following the documented recipe.
  - `timestamp` was the hour start, `distinct_id` was `installation:<id>`, both groups were present, and no content was sent.
  - With `ANALYTICS_ENABLED=false` the stub received 0 requests.
- `phc_` appeared 0 times in the api and worker logs.
- **Finding:** `organization.updated` uses the Membership actor. Renaming an Organization and deleting it within a second skipped the update. The worker processed it after the Membership cascaded away, logged `actor_not_found`, and the delivery SUCCEEDED without sending. This is the documented skip-and-log behaviour. The fix is to give `organization.updated` a User actor, as `organization.created` and `organization.deleted` already have.

### 2026-10-07 — AF-357 — Hourly message counts

- Delivered: `agent.messages.counted`, one event per Agent, platform and direction per closed hour, counts only.
  - It is sent by `MessageCountReporter` (`api/domains/analytics/message_counts.py`) from a new hourly CronJob.
  - It buckets by `created_at` (migration `6c3f9a2e8b41` adds the index).
  - The `uuid5(installation, agent:platform:direction:hour)` ids keep two platforms on one Agent distinct, and stay stable across re-runs.
  - `distinct_id` is the `installation:<id>` pseudo-person. Batches are capped at 500.
- Changed: `conversations/repository.py` (`hourly_message_counts`, `MessageCount`), `conversations/models.py` (index), migration, `analytics/message_counts.py`, `analytics/event_handlers.py` (group constants made public), Helm CronJob template and `analyticsMessageCounts.schedule`, Make target `report-message-counts`, `product-analytics.md`, `operations.md`, `README.md`, `INDEX.md`.
- Verified:
  - The new `test_message_counts.py` tests pass:
    - counts across two platforms and both directions, bucketed by arrival time
    - exact payload and ids
    - re-run ids
    - batch splitting
    - nothing sent while disabled
    - the previous-hour calculation
  - `test_message_created_at_index_migration.py` passes, and there is a single Alembic head.
  - Render check: the CronJob is absent by default and for `"false"`, present for `true` and `"true"`, with the right schedule and command. Helmfile gives unset → absent, true → present, false → absent. `helm lint` is clean.
  - A local `main()` run reached `Config` but stopped on missing budget settings in the developer `.env`, so the entrypoint is verified in the cluster E2E instead.
- Follow-up: local E2E of all new events and the CronJob, then the production confirmation.

### 2026-10-07 — AF-357 — user.signed_up

- Delivered: `user.signed_up` (platform scope, User actor and subject, payload `user_id`), sent to `product_analytics.posthog` only.
  - The new `PasswordResetTokenRepository.redeem` replaces the two separate saves in `_apply_new_password` with one locked transaction: token and user, then the password, token used, and the event when this is the first invite acceptance.
  - That also makes a concurrent double accept impossible.
  - Known gap: an invitee who first enrolls through forgot-password emits no `user.signed_up`.
- Changed: `events/catalog.py`, `auth/repository.py` (`PasswordResetTokenRepository` now injects `OutboxMessageRepository`), `auth/service.py`, `analytics/event_handlers.py`, `product-analytics.md`, `domain-events.md`.
- Verified:
  - The new `test_user_signed_up_event.py` tests pass: the first accept, a reused token, a password reset, and an atomic rollback when the event write fails.
  - The wiring row passes.
  - The regression suites pass: `test_auth_flow_extended`, `test_organization_members`, `test_platform_admin_operations`, `test_set_password` (79 passed).
- Follow-up: hourly message counts.

### 2026-10-07 — AF-357 — user.logged_in

- Delivered: `user.logged_in` (platform scope, User actor and subject, payload `user_id` and `method: "password"`), sent to `product_analytics.posthog` only, with the installation group only.
  - The login logic moved from the route into `AuthService.login`. It records the event after the credential check through `OutboxMessageRepository.create` and enqueues it.
  - A recording failure is logged and the login still succeeds.
  - Failed logins, refresh and API-key requests record nothing.
- Changed: `events/catalog.py`, `auth/service.py` (now injects `OutboxMessageRepository` and `EventDeliveryDispatcher`), `auth/routes.py`, `analytics/event_handlers.py`, `product-analytics.md`, `domain-events.md`, `operations.md` (outbox volume note).
- Verified:
  - The new `test_user_logged_in_event.py` tests pass: success, wrong password and unknown email, refresh, API key, and outbox failure.
  - The wiring row and `test_auth.py` pass.
  - The regression suites pass: `test_auth_flow_extended`, `test_set_password`, `test_api_keys`, `test_platform_admin_operations` (51 passed).
- Follow-up: `user.signed_up`.

### 2026-10-07 — AF-357 — organization.deleted

- Delivered: `organization.deleted` (organization scope, User Actor = the deleting Owner, payload `organization_id`), sent to `product_analytics.posthog` only.
  - The new `OrganizationRepository.delete_with_event` locks the Organization, stages the event, deletes the row (Memberships cascade in the database) and commits in one transaction.
  - The service enqueues the delivery ids.
- Changed: `events/catalog.py`, `organizations/repository.py`, `organizations/service.py`, `analytics/event_handlers.py`, `product-analytics.md`, `domain-events.md`.
- Verified:
  - The new `test_organization_deleted_event.py` tests pass. The Organization and its Memberships are gone while the event and its delivery remain and are enqueued. Processing the delivery sends the event as the deleter with the organization group.
  - The wiring row passes, and the existing delete and permission tests still pass (`test_organization_operations_extended`).
- Follow-up: `user.logged_in`.

### 2026-10-07 — AF-357 — organization.updated

- Delivered: `organization.updated` (organization scope, the actor from `resolve_actor_identity`, payload `organization_id` and `changed_fields`), sent to `product_analytics.posthog` only.
  - It is staged in the `update_organization` session only when the name or description differs from the stored value. The comparison runs before the values are applied.
  - Delivery ids from it and from `organization.model_allowlist.changed` are collected and enqueued together.
- Changed: `events/catalog.py`, `organizations/service.py`, `analytics/event_handlers.py`, `product-analytics.md`, `domain-events.md`.
- Verified:
  - The new `test_organization_updated_event.py` tests pass: a rename records the changed names, resending the same values records nothing, and a rename with an allowlist change enqueues both events' deliveries.
  - The wiring row passes.
  - The existing suites still pass: `test_organization_update_models`, `test_organizations`, `test_organization_operations_extended`.
- Follow-up: `organization.deleted`.

### 2026-10-07 — AF-357 — organization.created

- Delivered: `organization.created` (organization scope, User Actor, payload `organization_id` and `created_by_user_id`), sent to `product_analytics.posthog` only.
  - It is staged in the creating transaction for `POST /organizations` (actor: the creator) and for `POST /platform/users` (actor: the Platform Administrator, whose context the route now passes to `UserService.create_platform_user`).
  - Delivery ids are enqueued after commit.
- Changed: `events/catalog.py`, `OrganizationRepository.create_for_user` (now takes the actor and returns the delivery ids) and the new `stage_organization_created`, `OrganizationService`, `UserService`, `users/routes.py`, `analytics/event_handlers.py`, `product-analytics.md`, `domain-events.md`.
- Verified: the new tests in `test_organizations.py`, `test_users.py`, `test_product_analytics_handler.py` and the wiring test. The regression suites still pass (`test_platform_admin_operations`, `test_organization_members`, `test_api_keys`, `test_organization_operations_extended`, `test_user_listing_scope`: 97 passed).
- Follow-up: `organization.updated`.

### 2026-10-07 — AF-357 — Platform-scoped analytics

- Delivered: `ProductAnalyticsHandler` accepts platform-scoped events (`organization_id` null) with a User Actor. They are sent with only the `installation` group and no `organization_id`. A Membership Actor without an Organization is still skipped. No platform event subscribes the handler yet; `user.logged_in` and `user.signed_up` will.
- Changed: `api/domains/analytics/event_handlers.py`, `product-analytics.md` (Groups invariant, common property set).
- Follow-up: `organization.created`.

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
