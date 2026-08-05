# AF-167 — Extend Domain Event coverage for the Security Audit Record projection

## Context

AF-167 ("Add Audit Logging") was blocked for weeks while AF-219/AF-220 (Domain
Event/Outbox/Dramatiq foundation) and then AF-237 (Platform admin views) shipped
independently. AF-237 already built a real, durable `security_audit_record`
table and an idempotent `SecurityAuditProjection` handler
(`api/domains/events/security_audit.py`), and already wired 6 events into it
(RBAC role changes, agent access grant/revoke, agent general-access changes,
platform-privilege grant/revoke). A separate new ticket, **AF-249** (unassigned,
To Do), now owns the read-side "unified searchable Security Audit Record
explorer" UI/API that AF-167's original PR (#75, now closed) had built as a
fully parallel, now-redundant system.

Given that, AF-167's remaining useful scope ("Option 1", confirmed with the
user) is: **broaden which mutations produce a Domain Event that feeds the
existing `SecurityAuditProjection`** — no new table, no new UI, no new
handler. The branch was reset to a fresh checkout of `origin/staging`
(old branch/PR abandoned) since almost none of the old PR's code is reusable
for this narrower scope.

Six mutation categories currently produce no Domain Event at all and are the
target of this work: Agent update, Agent delete, Agent Secret/credential
create+update+delete, Template create+update+delete, Organization
model-allowlist change, and Organization member add+remove.

## The established pattern (replicate exactly)

Every existing event-producing mutation follows one shape — see
[api/domains/agents/repository.py:392-434](api/domains/agents/repository.py:392)
(`create_with_creator_access`, the `AGENT_CREATED` emitter) as the reference:

1. One repository method opens `Session(self.delegate.engine, expire_on_commit=False)`.
2. It mutates business state in that session.
3. It calls `EVENT_REGISTRY.build_event(event_name=..., schema_version=1, occurred_at=datetime.now(UTC), organization_id=..., actor=actor, subject=SubjectIdentity(...), correlation_id=..., payload={...})`.
4. It calls `self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)`.
5. It captures delivery ids: `list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))`.
6. **One** `session.commit()`.
7. The calling service method does post-commit best-effort enqueue:
   `self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)`.

Actor identity: every call site already has `context: CurrentUserContext` in
scope (all six target service methods take it as a parameter today). Use
`resolve_actor_identity(context, organization_id)` from
[api/domains/events/dispatch.py:15-23](api/domains/events/dispatch.py:15) —
exactly as `create_agent`/`start_agent`/`stop_agent`/`change_role` already do.
`SubjectIdentityType` already has `AGENT`, `TEMPLATE`, `ORGANIZATION`,
`MEMBERSHIP` members ([api/domains/events/models.py:23-30](api/domains/events/models.py:23)) —
no enum/model change needed anywhere in this plan.

All new events route to the existing `SECURITY_AUDIT_HANDLER` — no new
handler. `docs/features/domain-events.md`'s "Initial event catalogue" section
should be extended to list the new events (required by the doc's own "Change
impact" section).

## New events and their target mutations

### 1. `agent.updated` — [api/domains/agents/service.py:1037](api/domains/agents/service.py:1037)

`update_agent` ends with a plain `self.repository.save(agent)` — no
scaffolding. Add `AgentRepository.update_scalar_fields_with_event(agent, *,
actor, correlation_id=None)`: re-select the row `with_for_update()`, diff
**only** the scalar fields `update_agent` mutates directly on the row today
(`name`, `model`, `approval_mode`, the template pin fields), build
`field_changes: dict[str, dict[str, Any]]` (matches the
`docs/features/domain-events.md` `AGENT_RENAMED` example shape), stage the
event, one commit. **If no tracked field actually changed value, stage no
event** (no-op) — an update touching only skills/secrets/platform-config
already gets its own coverage from the other new events below, so an empty
`field_changes` here would be a confusing no-content audit row.

Payload: `organization_id`, `agent_id`, `field_changes`, `actor_display`,
`subject_display`. Nested platform config (Slack/Teams/Telegram
tokens/config), skills, and secrets are explicitly **out of scope** for this
event's diff — they mutate via separate `save_*` calls in `update_agent`, not
the final `self.repository.save(agent)` line this targets, and some contain
near-secret data unsafe to diff into a payload.

### 2. `agent.deleted` — [api/domains/agents/service.py:1614-1615](api/domains/agents/service.py:1614)

`delete_agent` soft-deletes via `agent.deleted_at = ...; self.repository.save(agent)`.
Add `AgentRepository.soft_delete_with_event(agent_id, *, actor,
correlation_id=None)`, modeled on `_record_agent_event`
([api/domains/agents/repository.py:458-514](api/domains/agents/repository.py:458)):
re-select `with_for_update()`, set `deleted_at`, stage event, one commit.
Payload mirrors `AgentCreatedPayload` (`organization_id`, `agent_id`,
`agent_name`, `platform`, `runtime`) plus `actor_display`/`subject_display`
(needed here since, unlike `AGENT_CREATED`, this event has a handler).
Keep today's ordering: k8s teardown / Slack-token-clear run first as they do
now, soft-delete-with-event last — an event only fires once the row is
actually gone, matching current behavior where teardown failure already
prevents the save.

### 3. Agent Secret/credential changes — `agent.secret.added` / `agent.secret.updated` / `agent.secret.removed`

Three separate event names (confirmed) — matches the existing
`agent.access.granted`/`.revoked` naming convention. Target call sites:
`create_agent`'s initial-secrets loop, `update_agent`'s
delete/update/create-secret loops
([api/domains/agents/service.py:972-1029](api/domains/agents/service.py:972)).
Add `AgentRepository.save_secret_with_event(secret, *, event_name,
organization_id, agent_name, actor, correlation_id=None)` and
`delete_secret_with_event(agent_id, provider, *, organization_id, agent_name,
actor, correlation_id=None)`. `organization_id` and `agent_name` must be
passed explicitly — `AgentSecret` has no `organization_id` column and no name
field, but both are already in scope at every call site.

**Payload must never include `secret.content`** (Fernet-encrypted blob). Build
it allowlist-style from exactly the fields the codebase already treats as safe
to expose — the same set used by `AgentSecretRead`
([api/domains/agents/models.py:682-687](api/domains/agents/models.py:682)):
provider, secret name, shared-credential linkage, plus
`organization_id`/`agent_id`/`actor_display`/`subject_display`. One shared
Pydantic payload model (`AgentSecretChangedPayload`) covers all three event
names — the event name itself carries the add/update/remove distinction, no
per-event model needed.

**Field-naming constraint discovered during implementation:** the registry's
sensitive-key filter (`api/domains/events/registry.py` `_is_sensitive_key`)
rejects any payload key containing `secret` or `credential` as a substring —
this is an existing, deliberate defense-in-depth check, not something to work
around. `AgentSecretChangedPayload`'s fields are therefore named `record_id`
(not `secret_id`), `label` (not `secret_name`), and `shared_reference_id`
(not `shared_credential_id`) — same data, non-colliding key names.

`delete_secret_with_event` must capture `provider`/`secret_name`/
`shared_credential_id`/`id` off the row **before** deleting it (needed for the
payload). Granularity: one event per secret, one commit per secret call — matches
today's per-item `save_secret`/`delete_secret` call shape; do not try to batch
a multi-secret request into one transaction.

### 4. Templates — `template.created` / `template.updated` / `template.deleted`

`TemplateRepository` ([api/domains/templates/repository.py](api/domains/templates/repository.py))
currently has only a `delegate` field — add `outbox_repository:
OutboxMessageRepository` (pure additive; it's `@inject @singleton`, no DI
provider file to touch). `TemplateService` needs a new
`event_delivery_dispatcher: EventDeliveryDispatcher` field (it has none
today); `context: CurrentUserContext` is already a parameter on
`create_template`/`update_template`/`delete_template`.

**Decided:** `save_template`
([api/domains/templates/repository.py:155-157](api/domains/templates/repository.py:155))
and `save_org_template_skills`
([:159-177](api/domains/templates/repository.py:159)) are two separate
commits today. These collapse into **one atomic session**: the new
event-emitting repository methods (`save_template_with_created_event`,
`save_template_with_updated_event`) open one `Session`, add/flush the
template row, port the diff-sync loop body from `save_org_template_skills`
into the same session to sync `AgentTemplateSkill` rows, stage the event,
then one `session.commit()`. The standalone `save_org_template_skills` call
in `create_template`/`update_template`'s service-layer call sites is removed
— the new repository methods take the skills map as a parameter instead.

`template.updated`'s `field_changes` is scoped to **`template_name` and
`description` only** (confirmed) — explicitly excluding the markdown prompt
bodies (`soul_md`, `tools_md`, etc.), which can be large free text and are
closer to content than security-audit material.

`template.deleted` (`purge_org_template_lineage`,
[api/domains/templates/repository.py:436-461](api/domains/templates/repository.py:436))
is already one atomic session — add `outbox_repository` usage, capture the
latest version's `template.id` (used as `subject.id` — a purged lineage has
no single stable id, so the latest version stands in) and the full
`versions_deleted: list[int]` before the delete statement runs, stage
`template.deleted`, same single commit as today.

### 5. `organization.model_allowlist.changed` — [api/domains/organizations/service.py:197-215](api/domains/organizations/service.py:197)

**Session stays in the service** (confirmed) — the existing
`with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:`
block in `update_organization` already atomically handles the
`allowed_models`/`flag_modified` logic; add `outbox_repository:
OutboxMessageRepository` to `OrganizationRepository` and stage the event
inside this same existing session, right before `session.commit()`, only when
`"allowed_models"` is present in `dump` and actually differs from
`organization.allowed_models` (capture the previous list **before** the
`setattr` loop mutates it). Add `event_delivery_dispatcher` to
`OrganizationService`; call `enqueue_immediate` after the `with Session` block
exits. Payload: `organization_id`, `previous_models: list[str]`, `new_models:
list[str]`, `actor_display`, `subject_display` — explicit before/after lists,
not a generic `field_changes` diff (single well-known field). No special
truncation logic; 16KB payload bound (`registry.py`) is generous for glob-pattern
lists — add a regression test with a realistic large allowlist instead of
guarding against it in code.

### 6. `organization.member.added` / `organization.member.removed` / `organization.ownership_transferred`

**Session stays in the service** (confirmed, consistent with #5).

A third event was added to this group after re-checking the plan against
[Jira comment 55160](https://aai-labs.atlassian.net/browse/AF-167?focusedCommentId=55160),
which explicitly lists "member add/remove, ownership transfer" as the
org/member mutations needing coverage — `transfer_ownership` was missing from
the original plan.

- `remove_member` ([api/domains/users/organization_users/service.py:310-339](api/domains/users/organization_users/service.py:310)):
  today calls `organization_user_repository.delete(membership)` (its own
  plain commit). Add `OrganizationUserRepository.delete_with_event(membership,
  *, actor, actor_display, correlation_id=None)`: open one session, capture
  `role`/`user_id` off the membership before deleting (needed for the
  payload, since the row is gone after), `session.delete(membership)`, stage
  `organization.member.removed`, one commit. `auth_service.revoke_pending_invites`
  stays where it is today, after `enqueue_immediate` — separate aggregate
  (invite tokens), doesn't need the same transaction.
- `add_member` ([api/domains/users/organization_users/service.py:222-264](api/domains/users/organization_users/service.py:222)):
  already shares one service-owned session across `auth_service.prepare_invite`
  and `organization_user_repository.save_with_session` today. Add a
  session-*accepting* (not session-opening) method to
  `OrganizationUserRepository`, e.g. `stage_member_added_event(session,
  membership, *, actor, actor_display, subject_display, correlation_id=None)
  -> DomainEventEnvelope`, called from inside `add_member`'s existing
  `with Session(...)` block right after `save_with_session`, with delivery
  ids captured the same way before the service's existing `session.commit()`.

- `transfer_ownership` ([api/domains/users/organization_users/service.py:341-361](api/domains/users/organization_users/service.py:341))
  → `OrganizationUserRepository.transfer_ownership`
  ([api/domains/users/organization_users/repository.py:218-244](api/domains/users/organization_users/repository.py:218)):
  already **one atomic session/commit** that demotes the old owner and
  promotes the new one — the cheapest of the three to wire up. Rename to
  `transfer_ownership_with_event` (or add an `actor`/`correlation_id` param
  to the existing method) and stage `organization.ownership_transferred`
  inside the existing session, right before its existing `session.commit()`.

Payload: `OrganizationMemberChangedPayload` (shared by `.added`/`.removed`) —
`organization_id`, `membership_id`, `user_id` (nullable — pending invites may
not have accepted yet), `role`, `actor_display`, `subject_display`.
`organization.ownership_transferred` needs its own payload,
`OrganizationOwnershipTransferredPayload`: `organization_id`,
`previous_owner_membership_id`, `previous_owner_user_id`,
`new_owner_membership_id`, `new_owner_user_id`, `actor_display`,
`subject_display`.

## Cross-cutting checklist

- `SecurityAuditProjection.supported_events`
  ([api/domains/events/security_audit.py:83-90](api/domains/events/security_audit.py:83)):
  add all 12 new `SupportedEvent(...)` entries (agent.updated, agent.deleted,
  3× agent.secret.*, 3× template.*, organization.model_allowlist.changed, 3×
  organization.member.*/ownership_transferred).
- `api/tests/unit/test_event_handler_registry_wiring.py:34-43`
  (`test_every_catalog_handler_name_has_a_registered_handler`): add the same
  12 event names to its tuple.
- `docs/features/domain-events.md`: extend the "Initial event catalogue"
  section with the new events.

## Tests (per event, following the checklist in `docs/features/domain-events.md`)

For **each** of the 12 new events:

1. **Unit — payload validation / secret rejection**, in
   `api/tests/unit/test_domain_events.py`: at least one test per new payload
   model exercising the registry's existing sensitive-key/size-bound checks
   against realistic field values (e.g. the secret payloads must be provably
   free of `content`; the allowlist payload should have a large-realistic-list
   regression test against the 16KB bound).
2. **Integration — one-transaction persistence**, in
   `api/tests/integration/test_outbox_messages.py`, mirroring
   `test_role_change_repository_operation_emits_audit_domain_event`
   ([api/tests/integration/test_outbox_messages.py:759-788](api/tests/integration/test_outbox_messages.py:759)):
   call the new repository method directly, assert exactly one outbox row
   with the expected payload shape and one `EventDelivery` row for
   `security_audit.projection`.
3. **Integration — full projection**, in the relevant domain's existing
   integration test file (`test_agents.py`, `test_templates.py`,
   `test_organizations.py`/`test_organization_members.py`), mirroring
   `test_platform_privilege_event_projects_to_durable_security_audit_record`
   ([api/tests/integration/test_platform_admin_operations.py:304-343](api/tests/integration/test_platform_admin_operations.py:304)):
   drive the mutation over real HTTP, pull the outbox message, mark it
   enqueued, run `EventDeliveryProcessor.process(delivery.id)` synchronously,
   assert the resulting `SecurityAuditRepository.get_by_event_id(...)` row's
   fields (`event_scope`, `organization_id`, `action`, `actor_id`,
   `subject_id`, `details`/payload).

Run via `make check-api` and `make test-api` per this repo's testing
convention (never `pytest`/`ruff`/`ty` directly).

## Critical files

- `api/domains/events/catalog.py` — 12 new event names + payload models + registrations
- `api/domains/events/security_audit.py` — `SecurityAuditProjection.supported_events`
- `api/domains/agents/repository.py` — `update_scalar_fields_with_event`, `soft_delete_with_event`, `save_secret_with_event`, `delete_secret_with_event`
- `api/domains/agents/service.py` — `update_agent`, `delete_agent`, secrets loops in `create_agent`/`update_agent`
- `api/domains/templates/repository.py` — add `outbox_repository`; new event-emitting variants of `save_template`/`purge_org_template_lineage`
- `api/domains/templates/service.py` — add `event_delivery_dispatcher`; `create_template`/`update_template`/`delete_template` call sites
- `api/domains/organizations/service.py` — `update_organization`'s existing session block
- `api/domains/organizations/repository.py` — add `outbox_repository`
- `api/domains/users/organization_users/repository.py` — `delete_with_event`, `stage_member_added_event`
- `api/domains/users/organization_users/service.py` — `add_member`, `remove_member` call sites
- `api/tests/unit/test_domain_events.py`, `api/tests/unit/test_event_handler_registry_wiring.py`, `api/tests/integration/test_outbox_messages.py`, `api/tests/integration/test_agents.py`, `api/tests/integration/test_templates.py`, `api/tests/integration/test_organization_members.py`
- `docs/features/domain-events.md`

## Verification

1. `make check-api` — ruff/format/ty clean.
2. `make test-api` — full suite green, including all new unit + integration
   tests above (payload validation, one-transaction persistence, and full
   outbox→handler→`security_audit_record` projection per event).
3. Manual spot-check against a real Postgres (scratch DB or local
   docker-compose dev env, per this repo's established pattern): trigger one
   mutation from each of the 6 categories (including ownership transfer)
   via the API, confirm a `security_audit_record` row appears with the
   expected `action`/`actor`/`subject`/payload after the delivery worker
   processes it.
