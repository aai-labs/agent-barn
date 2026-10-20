# Agent workflows

Status: WF01 authoring implemented; execution unavailable.
Source: [AF-388](https://aai-labs.atlassian.net/browse/AF-388), [WF01 scope](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067019322), [selected architecture](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067248652), [unified UI](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3066101773).
Delivery sequencing: [AF-387 change log](agent-workflows/CHANGELOG.md).

## Ownership and authority

A Workflow belongs to one Agent and inherits its Organization scope. Reads require
current Membership, visible undeleted Agent scope and `agent.read`; authoring
and archive require `agent.update`. Organization Owner/Admin implicit
Agent authority, custom Agent Access Roles, explicit access and additive Agent
General Access use the [existing RBAC contract](rbac/IMPLEMENTATION-BRIEF.md).
Viewers inspect definitions and immutable versions; Editors author them. Every
backend mutation checks current authority independently of UI controls. Missing,
cross-Organization, wrong-Agent and inaccessible definitions return 404; visible
resources with insufficient mutation permission return 403. Read-only Personal
API Keys cannot mutate. Actor and ownership identifiers are server derived.

Repository queries join the owning Agent and apply visibility before pagination
and totals. Versions reference their owning definition rather than duplicating
Agent/Organization ownership; callers cannot move a definition or version to a
different Agent. Soft deletion of the Agent conceals its complete workflow tree.
Hard aggregate deletion cascades to the authoring records.

## Saved definitions and validation

Creation explicitly saves immutable v1. A version is the complete schema-v1
snapshot: name, outcome description, ordered step identities/names/goals,
completion criteria, required inputs, optional per-step and final artifact
descriptions, capability requirements and review destination. Step order is array
order. Step UUIDs and input keys must be unique. Canonical UUID-shaped step identities
use the same GUID validation in the UI and API; the manual builder assigns fresh
step identities when steps are added. A workflow needs 1–50 steps;
inputs are bounded to 30 with lowercase keys, text/number/boolean type and a
required flag. Keys start with a letter and allow lowercase letters, digits,
hyphens and underscores, up to 64 characters. The editor derives an internal key
from the label: accents fold to ASCII, text becomes lowercase, apostrophes drop,
and runs of other punctuation or whitespace become hyphens. Keys that would not
start with a letter gain an `input-` prefix (or `input` when otherwise empty).
Labels with non-ASCII letters/digits that cannot be folded, or keys exceeding 64
characters, receive a deterministic eight-digit FNV-1a suffix; the key is truncated
to fit. Blank labels remain invalid. Normalization collisions are reported on the
later input label, naming the first matching input; suffixes reduce collisions
but uniqueness is still validated rather than assumed. Keys stay hidden in both
editing and saved inspection. Existing saved keys remain unchanged until their
label is edited. Names and descriptions cannot be blank and have bounded lengths.
Unknown fields and unsupported input/capability/destination codes are rejected.
Artifact descriptions are free text intentions, not generated files or format
support promises. Authoring does not compile or admit execution capabilities.
The descriptive capability vocabulary is reasoning/business_action/native_command;
none enables a run in WF01.

A new version is an append, never an edit of an old snapshot. The definition row
is locked, its expected revision checked, the next version inserted and its
revision incremented in one PostgreSQL transaction. Competing saves of the same
revision yield one new version and one 409; neither overwrites a snapshot.
PostgreSQL also enforces unique version numbers and rejects snapshot/identity
updates or direct version deletion while its definition exists. User deletion may
null creator provenance without rewriting content. Archive increments the
revision, retains all versions and prevents further authoring. There is no
unarchive or version-delete API in WF01.

Text limits (4,000 characters for descriptions, 200 for names) count Unicode
code points on the API and in the editor; saved snapshots are read back without
input limits. Validation returns actionable 422 errors. Stale revisions and archive conflicts
return 409. The editor retains its draft after validation, transport or conflict
failure; loading the current revision is an explicit action that keeps edits
and lists what the other save changed (name, outcome, steps, inputs, final
output) before another save replaces it.

## Manual workflow building

**Create workflow** opens the manual editor directly. Users enter the workflow
name and outcome once in Workflow details, then add steps, inputs and output
descriptions. Building does not save automatically; saving is explicit.
Natural-language draft generation is deferred to a separate PR by the delivery
scope update on 2026-10-15. This slice has no generation endpoint, model adapter,
background completion, polling state, generation record or model configuration.

## API

Base: `/api/v1/organizations/{organization_id}/agents/{agent_id}`.

| Route | Behavior |
| --- | --- |
| `GET /workflow-capabilities` | Authoring availability; execution always false; web review only |
| `GET /workflows` | Scoped paginated card summaries, including archives; no full snapshots |
| `POST /workflows` | Validated full snapshot; 201 immutable v1 |
| `GET /workflows/{id}` | Latest saved snapshot, revision, archive status and current allowed actions |
| `GET /workflows/{id}/versions` | Scoped paginated immutable snapshots, newest first |
| `POST /workflows/{id}/versions` | Full draft plus `expected_revision`; 201 new version or 409 |
| `POST /workflows/{id}/archive` | `expected_revision`; 204, versions retained |

Lists default to page size 20, maximum 100. List items retain definition metadata
and current allowed actions; their `version` contains provenance, name,
description, `step_count` and `input_count`, rather than a `draft`. PostgreSQL
projects those fields and counts directly from JSONB, avoiding full snapshot
transfer to the API or browser. Detail and version-history endpoints retain full
snapshots. DTOs use snake_case. Definition
`allowed_actions` contains `save_version` and `archive` only while enabled,
unarchived and permitted for the current actor. Read APIs remain available with
the authoring gate off. No run/start endpoint is registered in this slice.

## Platform authoring setting

Platform Administrators enable or disable authoring at **Platform Settings →
Workflows** (`/dashboard/platform/settings?section=workflows`). The switch uses an
explicit Save/Cancel flow and applies across all Organizations. It enables
manual creation, new versions and archive; it never enables execution or grants
Agent permissions. Saved definitions and history remain available through the existing read APIs
while disabled; the Agent Workflows UI is hidden.

`GET/PUT /api/v1/platform/settings/workflows` require the shared Platform Admin
authority, independently of Organization membership. Organization Owners/Admins
cannot manage this setting. Read-only Personal API Keys cannot change it. The
strict update body contains only the boolean `authoring_enabled`; reads include
that effective value and a nullable `updated_at`.

The singleton `platform_workflow_settings` row persists the choice, update time
and acting User. Before any choice is saved, `WORKFLOW_AUTHORING_ENABLED` provides
the deployment default (`false`). A saved choice overrides that default in both
directions and survives API restarts. Each capability/read/mutation request reads
the effective setting from PostgreSQL; saving needs no redeploy. UI affordances
in other sessions can retain the documented 30-second cached view, but the server
checks authoring admission on every mutation. Requests already admitted may finish.

Effective changes commit atomically with a Platform-scoped
`platform.workflow_authoring.changed` event for the Security Audit projection,
carrying previous/current booleans and safe actor/subject display snapshots.
Repeated saves of an unchanged choice do not emit another event. Saving the
current deployment default still persists that explicit choice.

## UI and configuration

The Agent’s Workflows tab opens `/dashboard/{orgId}/agents/{id}?tab=workflows`.
The tab and its content appear only when the installation capability enables
authoring. While disabled (or before capability loading first succeeds), Agent navigation omits
Workflows, and direct/legacy workflow links render the Agent’s default visible
tab without loading workflow definitions or history. This is UI visibility only:
saved data and the existing API read/authoring contracts are unchanged. A disabled
capability observed while the tab is open unmounts its view and local draft; a failed
capability refresh keeps the last known state, so the tab and draft stay.
It requires `agent.read`, independently of conversation/activity access. Existing
`/workflows` links redirect to the tab and preserve the selected `workflow` query.
The editor supports adding, removing, undoing and reordering steps.
Removing the last step offers an empty state and disables saving; undo
restores the most recently removed step and its edited fields/output description. Final and
per-step output switches and descriptions are editable. Saved overview and version
history expose actual snapshots. Discard/archive use the shared branded dialog.
Run is disabled with an explicit execution-unavailable message. Web review is the
only selectable destination until notification capabilities are delivered.

The workflow list uses individual cards with the outcome, step/input counts,
saved version and archive status. Each card opens the saved definition and the
grid adapts to narrow screens.

Saved overview and editing share a section rail inspired by the original workflow
view: numbered steps on the left and one focused detail panel on the right.
Workflow details, required inputs and outputs/review use the same rail. Selecting
another section preserves the complete draft; reordering keeps the selected step
identity, and adding or undoing removal selects that step. On narrow screens the
step rail scrolls horizontally. Overview and Version history are compact tabs;
archive lives in the workflow actions menu. A historical snapshot identifies its
version and offers a return to the latest version; editing always starts from
the latest snapshot. Numbered steps describe plan order, never execution status. Save validation names
one-based steps/inputs and the visible field labels, opens the first invalid
section and links each error to its section. Fields also show accessible inline
feedback after blur, and all invalid fields are revealed after a save attempt;
editing revalidates revealed fields without submitting. Both client and API validation retain
the draft; client validation prevents submission of an invalid draft. Removing a
step moves keyboard focus to Undo. If save authority disappears, the section rail
remains navigable for inspecting retained edits while authoring controls disable.

All workflow query keys include Organization and Agent identity, with structured
prefixes for each definition and its history. List/history components fetch only
while their view is mounted; the history is not prefetched by selecting a
workflow. Reads have a 30-second freshness window, no polling and no focus-based
refetch. Within that window a returned view can reuse a cached read; a remounted
stale view refetches. Cached permission affordances can consequently lag a grant
change until a new request, but backend authorization remains decisive on every
request. Observed access errors replace protected views.

Successful saves seed the exact detail cache from the server response, avoiding
an immediate redundant detail GET, and invalidate the scoped lists/history.
Archive invalidates the definition and history as well as its scoped lists.
Mutation 403/404/409 responses also invalidate the affected definition,
capabilities and lists; a 403 also refetches the Agent's own permissions, which
decide whether authoring controls stay enabled. Organization switching evicts workflow caches, while
page state is keyed by Organization/Agent so drafts cannot cross scope. List and
history pages use `workflowPage` and `workflowVersionPage` URL parameters, so
reloads and returning from a definition retain their position. Invalid,
nonpositive or unsafe-integer values fall back to page one. Page-one parameters
are omitted, and an out-of-range result offers a return to the first page.
Version page position is reset when opening a different definition or after a
successful save. Legacy `/workflows` redirects preserve these parameters. Leaving the Workflows tab discards its unsaved local
draft; save or discard changes before navigating away.

See [operations](../guidelines/operations.md#workflow-authoring-wf01) for the
installation gate and migration/rollback guidance.

## Change impact and deferred slices

Implementation lives in `api/domains/workflows/` and
`ui/src/features/workflows/`.
Schema migrations: `a38801c6e001` after `c42e91b7a603` creates authoring records;
`a38802d7f002` adds the Platform authoring setting. Merge revision `c32e42bb0396`
joins it with staging head `d72b85f19c40`. Changes to snapshots must
move DTO validation, migration where needed, UI Zod schemas, tests and this
specification together. Future execution must pin an immutable saved version,
validate actual run inputs and compile shipped capabilities before admission.

Runs, isolated execution, checkpoints, actual artifacts, business/native review,
notifications, provider adapters and fanout belong to later AF-387 slices.
Authoring or artifact descriptions imply none of those capabilities. No workflow
runtime image changes or release version bump accompany WF01.
