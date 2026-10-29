# Agent workflows

Status: WF01 authoring and WF02 bounded execution implemented and verified locally; steps return persisted text summaries. Merge and deployment are separate delivery steps.
Source: [AF-388](https://aai-labs.atlassian.net/browse/AF-388), [AF-389](https://aai-labs.atlassian.net/browse/AF-389), [WF01 scope](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067019322), [selected architecture](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067248652), [unified UI](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3066101773).
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
inputs are bounded to 30 with lowercase keys, text/number/boolean/file type and a
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
Artifact descriptions describe what the user wants to receive. The Agent uses the
step and final output descriptions to choose a useful format and publishes any
generated files as downloadable artifacts. Authors do not configure file-format
switches. Descriptions do not validate semantic content or promise format support;
the Agent must honestly report unmet criteria or publication failure. Authoring
does not compile or admit execution capabilities.
The descriptive capability vocabulary is reasoning/business_action/native_command.
It is descriptive only: it neither enables nor restricts what a step may do when run.

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
scope update on 2026-10-15. Manual authoring has no generation endpoint, model
adapter, background completion, polling state, generation record or model configuration.

## API

Base: `/api/v1/organizations/{organization_id}/agents/{agent_id}`.

| Route | Behavior |
| --- | --- |
| `GET /workflow-capabilities` | Independent authoring/execution availability; web review only |
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
the authoring gate off. Run/start operations are described under WF02 below.

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
and acting User. Before any choice is saved, authoring defaults to `false`.
The saved choice survives API restarts; there is no environment override. Each capability/read/mutation request reads
the effective setting from PostgreSQL; saving needs no redeploy. UI affordances
in other sessions can retain the documented 30-second cached view, but the server
checks authoring admission on every mutation. Requests already admitted may finish.

Effective changes commit atomically with a Platform-scoped
`platform.workflow_authoring.changed` event for the Security Audit projection,
carrying previous/current booleans and safe actor/subject display snapshots.
Repeated saves of an unchanged choice do not emit another event. Saving the
current default still persists that explicit choice.

## UI and configuration

The Agent’s Workflows tab, listed under Work in the Agent's navigation panel, opens `/dashboard/{orgId}/agents/{id}?tab=workflows`.
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
Run is disabled with an explicit message while execution admission is unavailable. Web review is the
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
joins it with staging head `d72b85f19c40`. Execution revision `a38901e8a003`
and current staging head `a4e9c2d7b615` join at no-op merge `f8740a67b788`. Changes to snapshots must
move DTO validation, migration where needed, UI Zod schemas, tests and this
specification together. Execution pins an immutable saved version and validates
actual run inputs; what a step may do is governed by the owning Agent's configuration.

Workflow-specific approval UI, notifications, provider adapters and fanout belong
to later AF-387 slices. No release version bump accompanies WF02.

## WF02 execution and outputs

WF02 runs each step as a new session in the owning Agent and persists text results
in PostgreSQL. A step is governed by whatever is configured on the Agent: its
tools, connected Integrations, approval mode and spend limits. A step can do
exactly what the Agent can do in chat, under the same rules, including acting
unattended wherever the Agent may act unattended in chat. [Agent artifacts](agent-artifacts.md)
adds optional shared chat/workflow files with private Garage/S3 bytes, scoped
publication, immutable ID/checksum handoff, attachments and retention. The saved
`artifact_description` and `final_artifact_description` fields guide the requested
output; text-only results remain supported without storage. Every completed step
reports its actual result in its summary, bounded to 4,000 characters, including
facts later steps need. The last step's summary also serves as the final result.

Execution is independent of the authoring setting. An Editor explicitly reviews
a saved version's typed inputs and starts it. The Agent must be running. A run
pins version, initiator User/Membership, inputs and the Agent's runtime kind; it
does not pin a runtime image or model, because the Agent's current configuration
applies. Historical saved versions are addressable directly. Start identities are
unique per definition; identical retries return the original run, including after
archive, while changed actor/version/inputs return 409. Starts serialize per Agent across its definitions for transactional consistency.
Workflow admission does not impose an active-run concurrency cap; multiple runs
can execute as separate sessions in the owning Agent.
Declared step capabilities do not gate admission. All subordinate reads use current Agent visibility before
totals/pagination; start/cancel require `agent.update`, including custom and
general Agent Access. Read-only keys cannot mutate. Viewers can inspect run
progress, summaries and history. Run detail defaults to the overall run view,
labelled Result ready after success and Run overview otherwise. The navigation card
uses an icon, descriptive subtitle and chevron, with an accent background when selected.
Successful runs retain the completion banner above the Agent's final summary. Selecting a step
in the numbered rail replaces the main panel with that step’s persisted Markdown
result, or its current waiting/in-progress/no-result state. The overall-view
control stays visible so users can return to the final summary. Selection stays
within the current run; changing runs resets to the overall view. Results use the
shared chat Markdown viewer. A compact Time taken card replaces the activity log. Each completed step shows
wall-clock time from its first attempt admission to its persisted checkpoint,
including dispatch waiting and retries. The API exposes nullable `started_at` and
`completed_at` fields derived from existing attempts/checkpoints; no migration is
needed. Unfinished steps show their status, and missing timestamps are unavailable
rather than zero. Total run time spans run creation through settlement and includes
queueing and retries. Selecting a completed step also shows its duration. The
history API remains available, but the run screen no longer fetches the event log. Step-rail connectors join the centers and edges of adjacent markers. Run detail uses one breadcrumb row that retains the selected workflow name. Its
Runs control clears only the selected run and selects the owning workflow’s Runs
view. Overview, Runs and Version history use `workflowView=overview|runs|history`
as their source of truth; an absent or invalid view falls back to Overview. Tab
changes and opening/closing runs add browser-history entries without scrolling.
Run-list pagination uses `workflowRunPage`; returning from a run retains that page.
Reloads, direct links and browser back/forward preserve the selected view and
workflow. The legacy workflow URL redirects preserve these parameters. The focused
workflow layout stays consistent across its overview, list, history and run detail
so returning to Runs does not reintroduce the surrounding Agent header.


The PostgreSQL ledger comprises `workflow_run`, `workflow_attempt`,
`workflow_checkpoint` and `workflow_history`. Each transition stages a safe
`workflow.run.changed` Domain Event in the same transaction. After commit, the
service or controller immediately enqueues the staged delivery IDs; a broker
outage leaves durable pending deliveries for recovery. Its handler advances
the run and sends a newly admitted step to the Agent's private trigger server
(`POST /agent-triggers/v1/workflow-steps` on port 8082, authenticated with the
Agent's trigger key). The scheduled pass recovers missed wakeups once per minute.
Each attempt is sent at most once: `dispatched_at` records the Agent's acceptance,
and the trigger server commits an attempt receipt in its existing PVC-backed SQLite
journal before file I/O or runtime execution. The same attempt is refused even
after callback loss or process restart. A crash after receipt commit can leave
unexecuted work blocked; it does not authorize replay. Receipts contain only
attempt UUIDs and remain with the Agent volume. Each
completed step checkpoints its summary and step identity. Subsequent attempts
receive those summaries and the pinned inputs within a bounded context packet;
completed steps are never replayed to reconstruct context. Oversized context is
rejected rather than silently truncated.

The trigger server starts a new runtime session (`workflow-<attempt id>`): Hermes
through `/v1/runs` with its event stream, OpenClaw through
`/v1/chat/completions`. The Agent replies with a JSON summary; plain prose is
accepted as the summary. Machine routes at `/workflow-runtime/v1/attempts/{id}`
(`handoff`, `result`, `failure`) are outside the product API and public discovery.
A derived capability binds one attempt/generation. Handoff and outcome admission
check current initiator authority, Agent lifecycle, generation, attempt state and
deadline under the run lock. A reported failure or unmet criteria blocks the run.
An attempt exceeding its 15-minute deadline is fenced, a stop is requested and
the run blocks with an uncertain-outcome reason. No unfinished step is automatically
replayed: session end, callback loss and stop acknowledgement do not prove absence
of external effects. Inspect effects before explicitly starting another run;
there is no generic resume/reconciliation API in this slice. When the Agent asks
for a command approval, the session is stopped and the run becomes BLOCKED with the
reason, until a person resolves it in chat and reruns, or cancels. Workflow-specific
approval handling arrives with WF03. Agent stop or lost initiator authority pauses
progression; restarting the Agent does not resume it implicitly.

The result envelope accepts only `summary` and `criteria_met: true`. It does not
accept file payloads. Files use the shared artifact publication protocol before
completion; the checkpoint includes exact IDs/checksums of READY files from that
attempt. A completed result commits the checkpoint, progression and Domain Event
atomically. Exact duplicate results are acknowledged without
replaying progression; changed or stale results are rejected.

Cancellation records CANCELLING before stopping. New handoff/result admission fails
immediately; the trigger server is asked to stop the session (best effort, which
stops a Hermes run) and CANCELLED is recorded. Work the session already performed
is not undone. Completed summaries remain
available. Soft deletion conceals the run tree and fences/stops attempts. Existing
hard Agent/Organization deletion cascades workflow-owned records. Active runs
retain their checkpoint summaries. Settled inputs, checkpoints and content-bearing
history expire after the module-owned 90-day retention period, while run status
and metadata remain. File retention and purge are independent and follow the
[shared artifact lifecycle](agent-artifacts.md#retention-deletion-and-recovery).

The product API adds `POST /workflows/{id}/runs`, `GET /workflow-runs` (optional
`workflow_id`), `GET /workflow-runs/{id}`, `GET /workflow-runs/{id}/history` and
`POST /workflow-runs/{id}/cancel` with `expected_revision`. Collections retain the
standard 20/100 pagination bounds. Server-derived `allowed_actions` controls
cancellation with independent backend authorization. Artifact routes, generic
resume and approvals are not exposed in WF02.

The Workflows UI includes explicit input review, a Runs view, durable step
progress/history and cancellation confirmation. `workflowRun` retains the run in
the URL. Queries include Organization/Agent identity, refetch on focus, poll
queued/running/cancelling mounted views every three seconds and stop on parked
(paused/blocked), terminal, error or unmounted views. Focus refetch and mutations
still refresh parked views. Start retries retain their identity and inputs. Access errors replace
protected run content. Authoring retains its existing cache behavior.

Run screens use the agreed Workflow Playbook layout: full-page start/run views,
a breadcrumb, run header with status badge, a Steps rail, summaries, run activity
and Keep running/Cancel run confirmation. The shell owns the page frame and section navigation. The Agent mobile header
and section title remain mounted but hidden while a run or its start screen is open. Run detail returns
each completed step's `summary`, shown under “What each step did”, and a
`final_summary` once succeeded, shown with the chat Markdown viewer on the
completion card. The last step is excluded from the per-step card on success to
avoid repeating its text. Run and selected-step file attachments are delivered
through the shared [Agent artifact service](agent-artifacts.md) alongside summaries.
Dedicated preview pages, approvals and messaging remain follow-ups.

## AF-389 acceptance dependencies

PR [#326](https://github.com/aai-labs/agent-barn/pull/326) is merged into
staging. This local integration slice closes automatic replay of failed/expired
attempts and repeat trigger admission after restart. Live Agent-session execution,
OpenClaw stop/quiescence and run-read-policy coordination still need acceptance.
Callback/storage fencing does not prove tools stopped or that external writes are
safe to repeat. Artifact and run reads retain the current `agent.read` boundary.

## File workflow inputs and results

A saved input with `type: "file"` accepts exactly `{artifact_id, checksum}` at run
start. People select a READY artifact belonging to the same Agent or upload through
the existing human artifact stage/content endpoints. Upload does not start a run;
leaving the start screen keeps a successfully uploaded Agent artifact under ordinary
retention. Failed uploads never become selectable. The start screen retains prior
selections after upload/start failure and disables starting during uploads.
File inputs span the form width, with separate artifact-selection and upload
actions. A selected shadcn Attachment card exposes download and removal; removal
clears the input without deleting the stored Agent artifact. Uploads show their
pending attachment state without replacing a prior selection until publication
succeeds. The native file control is hidden behind the labeled upload action.

Run start checks `agent.update`, resolves current scoped ownership and READY state,
validates the lowercase SHA-256, and acquires run pins in the same transaction as
run creation and its outbox event. Any invalid selection rolls back all pins and
the run. It records canonical filenames/sizes alongside IDs/checksums in immutable
`inputs`; callers cannot supply those metadata fields. Same-request retries reuse
the original run; changed file identity/checksum conflicts. At most 16 file inputs
and the shared 16,000-byte run file-reference budget apply. No database migration
is needed: existing immutable JSON snapshots/inputs and artifact references carry
the additive fields; schema-v1 text definitions keep their behavior.

Each handoff contains a deduplicated manifest of run inputs and accepted earlier
checkpoint outputs. The trigger retrieves actual bytes into a fresh temporary
workspace directory using UUID filenames, checks each pinned checksum, and supplies
verified local paths to the step. Retrieval requests carry the attempt ID and must
find an active pin for that run; current initiator, Agent, generation and deadline
are checked before each new link and again after downloads before runtime start.
Download, integrity or admission failure prevents starting the session and parks
the run rather than silently substituting summaries. The final assembled prompt
must fit 64,000 UTF-8 bytes. Temporary inputs are removed when the trigger finishes;
the owning Agent remains a shared filesystem/trust boundary, not a session sandbox.
Already issued bearer URLs and bytes already read retain the existing artifact
revocation limitations.

Completion persists exact published output references and the step output
description in the accepted checkpoint. Every published file is downloadable,
regardless of whether a description was supplied. The Agent chooses whether the
requested deliverable needs files and reports unmet criteria if it cannot produce
or publish them. There is no author-selected file type or file-count completion
gate. Earlier files are available as inputs; they are not silently promoted to
final outputs. The service verifies published bytes, not whether a file's content
satisfies free-text criteria. `steps[].artifacts` exposes accepted checkpoint outputs;
`final_artifacts` contains only the successful last checkpoint's files and
`final_output_description` preserves the requested deliverable. Failed/unfinished
attempt publications remain visible separately as attachments, never as accepted
or final results.

The result view shows Run input files and Final outputs. A selected step shows
Step input files (including earlier accepted outputs) and Step outputs. Each
output appears once within its view, using the same icon cards as Agent Artifacts
and input selection; checksums remain internal to immutable references and byte
verification. Fresh authorized downloads retain file-specific failures. An
**All artifacts** navigation item below the steps opens the run-wide publication
collection, including unfinished-attempt files, with accepted step/final outputs
labeled. This collection is separate from the summary/step panes.
The selected view is one continuous bordered panel: summary/detail, file sections
and timing are grouped inside it with internal separators. The panel stretches to
at least the navigation height, so a desktop connector always meets its visible
edge even when file sections are absent or the artifact collection is short.
Connectors are hidden in the stacked mobile layout.
Run input and output pins use the shared artifact lifecycle: paused/blocked runs
retain them; success/cancellation releases them transactionally and starts the
ordinary retention period. Cancelling or losing access fences new handoffs,
workflow links, publication and completion without undoing tools or retracting
previously issued bearer links. Cancel a parked run to release its pins. Text-only
workflows continue without storage. The Agent must not present an unpublished
path or prose as a downloadable file when publication fails.
