# Agent workflows

Status: WF01 authoring and WF02 bounded execution implemented and verified locally; steps return persisted text summaries. Merge and deployment are separate delivery steps.
Source: [AF-388](https://aai-labs.atlassian.net/browse/AF-388), [AF-389](https://aai-labs.atlassian.net/browse/AF-389), [WF01 scope](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067019322), [selected architecture](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067248652), [unified UI](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3066101773).
Organization ownership: [AF-439](https://aai-labs.atlassian.net/browse/AF-439), [decision record](../adr/2026-11-12-organization-owned-workflows-run-by-agents.md).
Delivery sequencing: [AF-387 change log](agent-workflows/CHANGELOG.md).

## Ownership and authority

A Workflow belongs to one Organization and is not tied to an Agent. A run is one
saved Workflow Version executed by one Agent, chosen when the run starts; the
Agent is the runner of the run, not the owner of the workflow. Terms follow
[`CONTEXT.md`](../../CONTEXT.md).

**Definitions.** Every accepted Member of the Organization (`organization.read`)
reads definitions, their immutable versions and the capabilities, and creates
workflows. The creating Membership is recorded on the workflow, and every Member
who reads a definition sees its creator's name and User and Membership
identifiers, including Members without `membership.read`. Saving a version,
changing the default Agent and archiving are limited to that creator and to
Members holding the Organization Permission `workflow.manage`, which Owners and
Admins hold; any other Member receives 403. A workflow of
another Organization, or one that does not exist, returns 404. Duplicating is
creating: any Member may save a copy, which they then own.

**Default Agent.** A workflow may name one default Agent. It only preselects the
Agent when someone starts a run; it grants nobody access, and whoever starts the
run may choose another Agent. Setting it requires the author to be able to read
that Agent. Reads return `default_agent_id` only to callers who can read the
Agent, and never for a deleted Agent; everyone else sees null.

**Runs.** A run is a subordinate resource of the Agent that runs it, under the
[existing RBAC contract](rbac/IMPLEMENTATION-BRIEF.md): Organization Owner/Admin
implicit Agent authority, custom Agent Access Roles, explicit access and additive
Agent General Access all apply. Seeing a run, its history and its approvals
requires `agent.read` on the run's Agent. Starting, cancelling, deciding an
approval and re-running require `agent.update` on it. A run on an Agent the
caller cannot read returns 404, like a run that does not exist; a readable run
without `agent.update` returns 403. Run lists return only runs on Agents the
caller can read, applied before pagination and totals.

**Deleted Agents.** Deleting an Agent does not remove or archive any workflow.
Its runs stay readable under the same `agent.read` rule, evaluated against the
deleted Agent's access settings, and report `agent_archived: true`; nothing more
can be done with them (cancel, decide and re-run return 409). A run that was
still active ends as cancelled.

Every backend mutation checks current authority independently of UI controls.
Read-only Personal API Keys cannot mutate. Actor, creator and Organization
identifiers are server derived. Versions reference their definition rather than
duplicating Organization ownership, and a definition cannot move to another
Organization. Organization deletion cascades to definitions and runs; hard
deletion of an Agent cascades to its runs and clears it as a default Agent.

## Saved definitions and validation

Creation explicitly saves immutable v1. A version is the complete schema-v1
snapshot: name, outcome description, ordered step identities/names/goals,
required inputs, capability requirements and review destination. Step order is array
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
later input's description, from which the label derives, naming the first matching input; suffixes reduce collisions
but uniqueness is still validated rather than assumed. Keys stay hidden in both
editing and saved inspection. Existing saved keys remain unchanged until their
label is edited. Names cannot be blank. The workflow description is optional;
descriptions have bounded lengths.
Unknown fields and unsupported input/capability/destination codes are rejected.
A step's goal states what the Agent should do, including anything it should
produce. The Agent uses it to choose a useful format and publishes any generated
files as downloadable artifacts. Authors do not configure file-format switches.
The goal does not validate semantic content or promise format support; the Agent
must honestly report unmet criteria or publication failure. Authoring does not
compile or admit execution capabilities.

The separate per-step `artifact_description` field is legacy. A create or save
that still sends it has its text appended to that step's goal as
`Output: <text>` and the field stored as null; if the combined goal would exceed
4,000 characters the request is rejected with 422 naming the step. Versions saved
earlier keep their stored `artifact_description`, which is still passed to the
Agent and shown on their runs as `output_description`.
Step instructions can include success criteria. Older saved completion criteria
remain visible and are passed to the Agent; new steps do not require them.
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
name and outcome once, optionally choose a default Agent, then add steps and
inputs. Building does not save automatically; saving is explicit.
Natural-language draft generation is deferred to a separate PR by the delivery
scope update on 2026-10-15. Manual authoring has no generation endpoint, model
adapter, background completion, polling state, generation record or model configuration.

## API

Base: `/api/v1/organizations/{organization_id}`. No workflow route is nested
under an Agent; the Agent that runs a run is a field of the run. The earlier
`/agents/{agent_id}/workflow-capabilities`, `/agents/{agent_id}/workflows…` and
`/agents/{agent_id}/workflow-runs…` routes are removed.

| Route | Behavior |
| --- | --- |
| `GET /workflow-capabilities` | Independent authoring/execution availability; web review only |
| `GET /workflows` | Paginated card summaries, including archives; no full snapshots. Each carries `default_agent_name` and `run_count`, both limited to Agents the caller can read. Filters: `created_by_me=true`, `archived=true\|false` |
| `POST /workflows` | `{draft, default_agent_id?}`; 201 immutable v1 |
| `GET /workflows/{id}` | Latest saved snapshot, revision, archive status, creator, default Agent and current allowed actions |
| `PATCH /workflows/{id}` | `{expected_revision, default_agent_id}` (null clears it); new revision, no new version, or 409. Sending the default it already has changes nothing and keeps the revision |
| `GET /workflows/{id}/versions` | Paginated immutable snapshots, newest first |
| `POST /workflows/{id}/versions` | Full draft plus `expected_revision`; 201 new version or 409 |
| `POST /workflows/{id}/archive` | `expected_revision`; 204, versions retained |
| `POST /workflow-runs` | `{workflow_id, agent_id, version_id, client_request_id, title?, inputs}`; 202 queued run |
| `GET /workflow-runs` | Paginated runs on Agents the caller can read, newest first. Filters: `workflow_id`, `agent_id`, `awaiting_decision=true`, `status=active\|settled` |
| `GET /workflow-runs/{run_id}` | One run with step progress, approvals and current allowed actions |
| `GET /workflow-runs/{run_id}/history` | Paginated history; `newest_first=true` reverses it |
| `POST /workflow-runs/{run_id}/cancel` | `expected_revision` |
| `POST /workflow-runs/{run_id}/re-run` | `client_request_id` only; see [Run again](#run-again) |
| `POST /workflow-runs/{run_id}/approvals/{request_id}/decision` | See [Workflow approvals](#workflow-approvals-af-390) |

Lists default to page size 20, maximum 100. List items retain definition metadata
and current allowed actions; their `version` contains provenance, name,
description, `step_count` and `input_count`, rather than a `draft`. PostgreSQL
projects those fields and counts directly from JSONB, avoiding full snapshot
transfer to the API or browser. Detail and version-history endpoints retain full
snapshots. DTOs use snake_case. Definition reads carry `created_by`
(`membership_id`, `user_id`, `name`; null once that Membership is removed) and
`default_agent_id`. Definition
`allowed_actions` contains `save_version` and `archive` only while enabled,
unarchived and permitted for the current actor (creator or Organization
Owner/Admin); the same authority covers changing the default Agent. Read APIs
remain available with the authoring gate off; create, save, default-Agent change
and archive return 409 while it is off.

Run reads carry `agent_id`, `agent_name` and `agent_archived`, the optional
`title` (up to 200 characters) given at start, and `name`, the workflow name of
the pinned version. `status=active` selects runs that have not settled;
`status=settled` selects Succeeded, Failed and Cancelled runs. Run behavior is
described under WF02 below.

## Platform authoring setting

Platform Administrators enable or disable authoring at **Platform Settings →
Workflows** (`/dashboard/platform/settings?section=workflows`). The switch uses an
explicit Save/Cancel flow and applies across all Organizations. It enables
manual creation, new versions, default-Agent changes and archive; it never
enables execution or grants Agent permissions. Saved definitions and history remain available through the existing read APIs
while disabled; the Workflows UI is hidden on the Organization page and on Agents.

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

The UI described in this specification is delivered by the AF-439 UI slice
([PR #368](https://github.com/aai-labs/agent-barn/pull/368)), which follows the
API slice; the [change log](agent-workflows/CHANGELOG.md#current-state) records
the state between the two.

Workflows are managed on the Organization's Workflows page,
`/dashboard/{orgId}/workflows`, reached from the Organization navigation. It has
two tabs. **Runs** lists runs waiting on an approval, then active and
recent runs, across every Agent the viewer can read. A viewer who can read an
Agent but not update it sees its pending approvals without being able to decide
them; each row names the Agent
that runs it. **Workflows** lists the saved workflows and is where workflows are
created, edited, duplicated and archived, and where a run is started. Edit and
Archive appear only for the creator and Organization Owners/Admins; Duplicate
opens the editor filled from the saved snapshot, names the copy
"<name> (copy)" and saves a new workflow.

The Workflows tab lists workflows that are not archived, with their count;
**Show archived** switches to archived ones only (`workflowFilter=archived`). The
API's `created_by_me` filter has no control on the page. A card's name opens the saved workflow, which has
three views: Overview (the saved snapshot), Runs (that workflow's runs on Agents
the viewer can read) and Version history. A card's menu also offers Open latest
run, which opens the newest run of that workflow the viewer can see.

Starting a run opens a dialog that asks for an optional run title and the Agent
to run as, listing running Agents the viewer can update. The workflow's default
Agent is preselected when it is among them; `?agent={id}` preselects another and
takes precedence. File inputs are chosen from the selected Agent's files, so they
unlock once an Agent is chosen and clear when it changes. A started run opens on
the Organization page. The dialog and the editor's default-Agent choices both
read the first 50 Agents of the Organization.

An Agent's Workflows tab, listed under Work in the Agent's navigation panel,
shows only that Agent's runs and the approvals waiting on them, and links to the
Organization page with the Agent preselected to start a run. Workflows are not
created or edited from an Agent. The tab requires `agent.read`, independently of
conversation/activity access. An Agent that has been deleted is shown by name
with an Archived marker and no link.

A count of the approval requests the viewer may decide is shown on the Workflows item
of the Organization navigation, across every Agent the viewer can read, and on
the Workflows item of an Agent's navigation panel, for that Agent.

The navigation item and the Agent tab appear only when the installation
capability enables authoring. While disabled (or before capability loading first
succeeds), navigation omits Workflows and a link to an Agent's Workflows tab
renders the Agent's default view. The Organization page stays reachable by URL:
it says authoring is disabled, offers no New workflow, and still lists saved
workflows and runs. This is UI visibility only: saved data and the existing API
contracts are unchanged. A failed capability refresh keeps the last known state,
so an open editor and its draft stay.

The editor is a dialog over the page. It holds the name, a description, the
default Agent (any Agent the author can see, or none), the steps and the inputs.
Default Agent choices are pills: No default, the first four Agents and the current
default when it is past them. The rest sit behind a "+N more" pill that opens a
searchable list. The list covers the first 50 Agents the editor loads.
Each step is a card with its number, move up/down controls, a remove control and
one text box, its prompt: what the Agent should do and produce. Every step is
open at once. A step has no name field; editing the prompt sets the stored step
name to its first line, whitespace collapsed and cut at a word to 80 characters,
which run lists and the step timeline show. A step whose prompt is not edited
keeps its saved name, and the API still requires one. Each input is a card with one field, its
description, above a footer holding a Text / File / Number / Yes or no segmented
type control, a Required checkbox and a remove control. Editing the description
sets the stored label to its first line (as for step names) and the key from that
label; the API still stores all three. The start-run form and saved overview show
the label, and the description under it only when it says more than the label. Steps have no type selector. Opening a version saved with a legacy
step output description folds that text into the step's text, as the API does on
save; no new version is written unless the author changes the plan. A change to
the default Agent alone saves no version.
The editor supports adding, removing and reordering steps. Removing a step with a
prompt asks first in the shared confirmation dialog; an empty step is removed at
once. There is no undo. Removing the last step offers an empty state and disables
saving. The step whose prompt or controls have focus shows its number in the
accent colour. Saved overview and
version history expose actual snapshots; a version saved with a legacy step
output description still shows it. Closing a changed draft, removing a step and
archiving use the shared branded dialog. Run is disabled while execution admission is unavailable
and for an archived workflow. Drafts are saved with Web review as their
destination; the editor offers no other.

The workflow list uses individual cards with the saved version, archive status,
description, the default Agent (name and avatar, or Unassigned) and a run count.
The default Agent is shown only when the viewer can read it, and the count covers
only runs on Agents the viewer can read, as the run lists do, so a card reveals no
activity on other Agents. Counts for a page of cards come from one grouped query
on the run table's workflow index. Run reads **Assign & run** when there is no
default Agent. A card's name opens the saved definition and the grid adapts to
narrow screens.

The saved Overview shows numbered steps beside one focused detail panel.
Overview, Runs and Version history are compact tabs; archive and duplicate live
in the workflow actions menu. A historical snapshot identifies its version and
offers a return to the latest version; running from it starts that version, and
editing always starts from the latest snapshot. Numbered steps describe plan
order, never execution status. Save validation names one-based steps/inputs and
the visible field labels, scrolls to the first invalid field and links each error
to its field. Fields also show accessible inline feedback after blur, and all
invalid fields are revealed after a save attempt; editing revalidates revealed
fields without submitting. Both client and API validation retain the draft;
client validation prevents submission of an invalid draft. If save authority disappears, the form is disabled and
keeps the retained edits visible.

Definition query keys include Organization identity, with structured
prefixes for each definition and its history; run queries add the Agent only as a
filter. List/history components fetch only
while their view is mounted; the history is not prefetched by selecting a
workflow. Definition reads have a 30-second freshness window, no polling and no
focus-based refetch. Within that window a returned view can reuse a cached read; a remounted
stale view refetches. Cached permission affordances can consequently lag a grant
change until a new request, but backend authorization remains decisive on every
request. Observed access errors replace protected views.

Successful saves seed the exact detail cache from the server response, avoiding
an immediate redundant detail GET, and invalidate the scoped lists/history.
Archive invalidates the definition and history as well as its scoped lists.
Mutation 403/404/409 responses also invalidate the affected definition,
capabilities and lists, so the server's current `allowed_actions` decide whether
authoring controls stay enabled. Organization switching evicts workflow caches, while
page state is keyed by Organization so drafts cannot cross scope.

The Organization page keeps its position in URL parameters: `workflowsTab`
(Runs or Workflows), `workflow` (the open saved workflow), `workflowView` (its
Overview, Runs or Version history), `workflowRun` (the open run),
`workflowFilter`, `workflowPage` (list), `workflowRunPage` (recent runs) and
`workflowVersionPage` (history), plus `agent` for the Agent to preselect when
starting a run. Reloads and returning from a definition retain list and history
positions. Invalid, nonpositive or unsafe-integer page values fall back to page
one. Page-one parameters are omitted, and an out-of-range result offers a return
to the first page. Version page position is reset when opening a different
definition. An Agent's Workflows tab uses `workflowRun` and `workflowRunPage`.
The earlier `/dashboard/{orgId}/agents/{id}/workflows` links still resolve: one
naming a saved workflow and no run opens that workflow on the Organization page,
and any other opens the Agent's Workflows tab, keeping the run it names.
Leaving the Workflows page discards its unsaved local draft; save or discard
changes before navigating away.

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
actual run inputs; what a step may do is governed by the configuration of the
Agent chosen for the run. Migration `e4b439a1c7d2` moves ownership to the
Organization; see [Organization ownership migration](#organization-ownership-migration-af-439).

Command approvals are delivered by [Workflow approvals](#workflow-approvals-af-390);
notifications, provider adapters and fanout belong to later AF-387 slices. No release version bump accompanies WF02.

## WF02 execution and outputs

WF02 runs each step as a new session in the Agent chosen for the run (a step continued after a
late [approval decision](#workflow-approvals-af-390) resumes its own session) and persists text results
in PostgreSQL. Every step of one run uses that same Agent. A step is governed by whatever is configured on the Agent: its
tools, connected Integrations, approval mode and spend limits. A step can do
exactly what the Agent can do in chat, under the same rules, including acting
unattended wherever the Agent may act unattended in chat. [Agent artifacts](agent-artifacts.md)
adds optional shared chat/workflow files with private Garage/S3 bytes, scoped
publication, immutable ID/checksum handoff, attachments and retention. Each
step's goal guides the requested output (a legacy `artifact_description` on an
earlier version is still passed along); text-only results remain supported
without storage. Every completed step
reports its actual result in its summary, bounded to 4,000 characters, including
facts later steps need. Summaries are requested as readable Markdown without expiring artifact download links; users download published files from the attachments. The last step's summary also serves as the final result.

Execution is independent of the authoring setting. A Member explicitly reviews
a saved version's typed inputs, chooses the Agent to run as and starts it, which
requires `agent.update` on that Agent. The Agent must be running. A run
pins its Agent, version, initiator User/Membership, inputs and the Agent's runtime kind; none of them can change afterwards. It
does not pin a runtime image or model, because the Agent's current configuration
applies. Historical saved versions are addressable directly. Start identities are
unique per definition; identical retries return the original run, including after
archive, while a changed Agent, actor, version, title or inputs return 409. Reusing
an identity against a different Agent is therefore a conflict, never a second run
and never a view of a run on an Agent the caller may not read. Starts serialize per Agent and per workflow for transactional consistency, so concurrent starts of one workflow on different Agents queue behind each other.
Workflow admission does not impose an active-run concurrency cap; multiple runs
can execute as separate sessions in the same Agent.
Declared step capabilities do not gate admission. All run reads use current visibility of the run's Agent before
totals/pagination; start/re-run/cancel require `agent.update` on it, including custom and
general Agent Access. Read-only keys cannot mutate. Viewers can inspect run
progress, summaries and history. Run detail defaults to the overall run view,
labelled Result ready after success and Run overview otherwise. The navigation card
uses an icon, descriptive subtitle and chevron, with an accent background when selected.
Successful runs retain the completion banner above the Agent's final summary. Selecting a step
in the numbered rail replaces the main panel with that step’s persisted Markdown
result, or its current waiting/in-progress/no-result state. The overall-view
control stays visible so users can return to the final summary. Selection stays
within the current run; changing runs resets to the overall view. Results use the
shared chat Markdown viewer. A compact Time taken card shows durations. Each completed step shows
wall-clock time from its first attempt admission to its persisted checkpoint,
including dispatch waiting and any attempts recorded by older versions. The API exposes nullable `started_at` and
`completed_at` fields derived from existing attempts/checkpoints; no migration is
needed. Unfinished steps show their status, and missing timestamps are unavailable
rather than zero. Total run time spans run creation through settlement and includes
queueing and any earlier attempts. Selecting a completed step also shows its duration. The
run screen also lists the run's history newest first as Activity (one `history?newest_first=true` read,
refreshed when the run's revision changes), so a failed attempt's
reason stays visible after an attempt ends; a completed step shows only
"Step completed" there, since its summary belongs to the step. While a step runs, the
single-run read includes `attempt` (number, start, deadline and
`server_time` (the API's clock, which the screen uses for elapsed and remaining time so a
skewed browser clock cannot distort them) and `agent_unresponsive`, true when the Agent has
not accepted the step after 60 seconds). The
rail and overview show the attempt and a live elapsed/timeout clock; an unresponsive Agent
shows a warning pointing to the Agent page to restart it. No migration is needed. Step-rail connectors join the centers and edges of adjacent markers. Run detail uses one breadcrumb row that retains the selected workflow name. Its
Runs control clears only the selected run and selects the owning workflow’s Runs
view. Overview, Runs and Version history use `workflowView=overview|runs|history`
as their source of truth; an absent or invalid view falls back to Overview. Tab
changes and opening/closing runs add browser-history entries without scrolling.
Run-list pagination uses `workflowRunPage`; returning from a run retains that page.
Reloads, direct links and browser back/forward preserve the selected view and
workflow. The legacy workflow URL redirects preserve these parameters. The focused
workflow layout stays consistent across its overview, list, history and run detail
so returning to Runs does not reintroduce the surrounding Agent header.


### Run again

`POST /workflow-runs/{id}/re-run` takes only a `client_request_id` (a body with
anything else is rejected with 422) and returns 202 with a new run. The server
copies the original run's pinned version and inputs, so a caller cannot change
either; the run's own version is used even when a newer one has been saved. It
runs on the same Agent as the original and keeps its title. It
follows the start path: `agent.update` on that Agent, a running Agent, a non-archived workflow
and the same admission, ledger and wakeup. A run whose Agent was deleted cannot be
repeated (409); start a new run and choose an Agent instead. Only a settled run (Completed, Failed
or Cancelled) can be repeated (409 otherwise), and not one whose inputs retention
has already removed (409). The original run, its history and its revision are not
touched.

The new run is a separate run with its own history. `workflow_run.rerun_of_run_id`
(nullable, self-referencing, `ON DELETE SET NULL`) records the original, exposed as
`rerun_of_run_id`; its first history entry has kind `RERUN_STARTED` and reads
"Re-run of run 12345678 using version N", where the id is the original's first
eight characters. The initiating User is whoever requests the re-run. A request
identity is unique per definition as for starts, and for a re-run it is bound to the
original run and the actor rather than to inputs: a retry with the same identity and
original returns the same run, even after retention has removed the original's inputs;
reusing it for another run or by another actor returns 409. The server advertises `rerun` in `allowed_actions` for a settled run
whose inputs remain, while its Agent is running and its workflow is not archived. A
BLOCKED or PAUSED run is still live and has no re-run; cancel it first.

In the UI, settled runs with `rerun` in `allowed_actions` show **Run again** in the
header when the overview's Run workflow would also be enabled (execution enabled and
available, and `agent.update`). It asks for confirmation, keeps one request identity
across retries from that run page, then opens the new run. A re-run shows "Re-run of
run …" linking to the original, and the Runs list marks it "Re-run".

The PostgreSQL ledger comprises `workflow_run`, `workflow_attempt`,
`workflow_checkpoint`, `workflow_history` and `workflow_approval_request`. Each transition stages a safe
`workflow.run.changed` Domain Event in the same transaction. After commit, the
service or controller immediately enqueues the staged delivery IDs; a broker
outage leaves durable pending deliveries for recovery. Its handler advances
the run and sends a newly admitted step to the Agent's private trigger server
(`POST /agent-triggers/v1/workflow-steps` on port 8082, authenticated with the
Agent's trigger key). The scheduled pass recovers missed wakeups once per minute, rotating bounded active and parked scans separately so parked runs cannot starve active runs and lifecycle/authority changes are still audited.
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
accepted as the summary. Malformed result envelopes receive one correction turn in the same session, instructing the Agent not to repeat work or use tools. If correction fails, the attempt reports a non-retryable failure rather than recording malformed output as successful prose. Machine routes at `/workflow-runtime/v1/attempts/{id}`
(`handoff`, `result`, `failure`) are outside the product API and public discovery.
A derived capability binds one attempt/generation. Handoff and outcome admission
check current initiator authority, Agent lifecycle, generation, attempt state and
deadline under the run lock. An explicit non-retryable failure fails and settles the run; a retryable failure blocks it for inspection.
An attempt exceeding its 15-minute deadline is fenced, a stop is requested and
the run blocks with an uncertain-outcome reason. No unfinished step is automatically
replayed: session end, callback loss and stop acknowledgement do not prove absence
of external effects. Inspect effects before explicitly starting another run;
there is no generic resume/reconciliation API in this slice. Command approvals follow
[Workflow approvals](#workflow-approvals-af-390). Agent stop or lost initiator authority pauses
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
available. Deleting an Agent fences and stops its attempts and cancels its active
runs; the runs remain readable as described under
[Ownership and authority](#ownership-and-authority). Hard Agent deletion cascades
that Agent's runs, and Organization deletion cascades definitions and runs. Active runs
retain their checkpoint summaries. Settled inputs, checkpoints, content-bearing
history and approval commands and guidance expire after the module-owned 90-day
retention period, while run status and metadata (including who decided each
approval, and when) remain. File retention and purge are independent and follow the
[shared artifact lifecycle](agent-artifacts.md#retention-deletion-and-recovery).

The run routes are listed under [API](#api). Collections retain the
standard 20/100 pagination bounds. Server-derived `allowed_actions` (`cancel`, `rerun`, `decide`) controls
those actions with independent backend authorization. Artifact routes and generic
resume are not exposed.

The Workflows UI includes explicit input review, a Runs view, durable step
progress/history and cancellation confirmation. `workflowRun` retains the run in
the URL. Queries include Organization identity, refetch on focus, poll
queued/running/cancelling mounted views every three seconds and stop on parked
(paused/blocked/awaiting approval), terminal, error or unmounted views. Focus refetch and mutations
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
Dedicated preview pages and approval notifications remain follow-ups.

## Workflow approvals (AF-390)

Terms follow [`CONTEXT.md`](../../CONTEXT.md): **Workflow Approval Request**,
**Approval Decision** and **Awaiting Approval**. Approvals extend the Agent's own
Hermes command approval; they never widen what its approval mode allows.

- **Coverage.** Hermes only. A command Hermes's policy does not flag (approval mode
  `off`, or `auto` judging it safe) runs unattended. OpenClaw raises no approval
  events, so its steps stay unattended under its `auto` policy; support is
  [AF-444](https://aai-labs.atlassian.net/browse/AF-444).
- **Live window.** On `approval.request` the trigger server reports the verbatim
  command to `POST /workflow-runtime/v1/attempts/{id}/approvals` and polls
  `GET …/approvals/{request_id}`. Only a verbatim `command` of at most 100,000
  characters is put to a person; anything else stops the step as needing attention.
  The API persists the request (run, step, attempt, session, Hermes run ID, command
  and its SHA-256) before review is exposed and keeps it decidable for
  `APPROVAL_LIVE_SECONDS` (270) counted from when Hermes raised it (`age_seconds`,
  from the event timestamp), ending before Hermes's 300-second auto-deny. A retried
  report of the same Hermes run and command returns the same request in whatever
  state it reached, with only the seconds left. The attempt deadline extends by the
  window; a live decision gives back the part not waited, so only time spent waiting
  for a person is added to the step's budget. Decide is offered only while the window
  is open. Approve is sent to Hermes as `once` and confirmed with `…/released`;
  `session` and `always` are never offered. Hermes's approval endpoint takes no request
  identifier, so `once` answers the run's active approval. Decline sends Hermes `deny`,
  stops the run, and only once both succeed resumes the same session
  (`resume_session`) with the decline and verbatim guidance.
- **Parking.** When the window closes the trigger server calls `…/park` before
  stopping the session. Park and decision serialize under the run lock: a decision
  that arrived first wins and is acted on; otherwise the request becomes `PARKED`, the
  attempt `STOPPED` and the run `AWAITING_APPROVAL`. Parked runs keep their file pins,
  never expire and can be cancelled.
- **Late decisions.** Approving or declining a parked request queues a new attempt
  that resumes the request's original session with a continuation prompt naming the
  command and decision (and guidance). A late approval never releases the command:
  if Hermes flags it again, a new live request is raised. Every resume sends
  `resume_require_history`; Hermes refuses a session with no stored history, and the
  attempt fails instead of continuing blind.
- **Bounds.** The third decline in one step blocks the run (cancel only) and fences
  the session.
- **Authority.** Deciding requires current `agent.update` on the run's Agent, checked at
  decision time; the decider is recorded. Runtime callbacks use the attempt
  capability and cannot decide. A late decision continues only while the Agent runs,
  the initiator keeps authority and the decider still holds `agent.update`; until then
  the run stays Awaiting Approval with the decision recorded. If the decider lost
  access, the request returns to `PARKED` for someone else to decide. Agent stops,
  managed updates and authority changes never lapse a parked request. Initiator
  authority loss or an Agent stop while a request is live pauses the run and lapses
  it; cancellation, a reported failure and settlement lapse open requests in the same
  transaction, so a stopped run never waits in the inbox. A decided, lapsed or stale
  request returns 409.
- **Interruption.** An attempt that expires (restart, lost session) blocks the run as
  uncertain and lapses its open request, like any expired attempt: Hermes may have
  denied the command itself and carried on, so an ended session is no evidence that
  nothing ran.
- **Reads.** Single-run reads carry the current step's latest request (`approval`) and
  every request of the run (`approvals`). List reads carry `approval` only while it
  awaits a decision; `awaiting_decision=true` lists only those runs.
- **UI.** A request awaiting a decision leads the run page: an amber approval card
  with the exact command, a live countdown or the paused explanation, optional
  guidance, and Approve/Decline when `allowed_actions` includes `decide`. The card
  states that Hermes supplies no target, parameters or rationale. The run badge reads
  "Waiting on you" (live) or "Awaiting approval · paused" and the step's rail marker
  turns amber. Decided commands stay on their step: rail chips count approvals and
  declines, and step detail lists each command, its outcome, decider and guidance.
  The Workflows navigation item shows the count of requests the viewer may decide,
  polled every 10 seconds; Viewers see the inbox as "Waiting on approval".
- **Inbox.** The Organization Workflows page's **Runs** tab leads with the runs
  waiting on approval across the Agents the viewer can read; an Agent's Workflows
  tab shows the same for that Agent alone. See [UI and configuration](#ui-and-configuration).

Migration `d1a390e7b2c4` adds `workflow_approval_request`, a partial index on open
(`LIVE`/`PARKED`) requests and the `AWAITING_APPROVAL` run state; downgrade blocks
parked runs. Agents need the updated trigger server (Agent update/restart) for live
approvals; older trigger servers keep the previous stop-and-block behavior. Refusing
an empty resumed session needs the updated Hermes base image; older images ignore
`resume_require_history`.

## Organization ownership migration (AF-439)

Migration `e4b439a1c7d2` follows `d1a390e7b2c4`. Snapshots are not rewritten and
the schema version stays 1; the pod-facing `/workflow-runtime/v1` routes, the
`workflow.run.changed` event, attempts, checkpoints, history and approval
requests are unchanged. No Agent update or restart is needed.

| Table | Change |
| --- | --- |
| `workflow` | Adds `organization_id` (required, cascades with the Organization), filled from the workflow's Agent. |
| `workflow` | Adds `created_by_membership_id` (nullable, set to null when the Membership is removed), filled with the Membership of whoever saved the workflow's first version while they are still a Member of the Organization, else the Organization's Owner, else its earliest Admin. |
| `workflow` | Adds `default_agent_id` (nullable, set to null when the Agent row is removed), filled with the workflow's Agent unless that Agent was already deleted. |
| `workflow` | Drops `agent_id`. |
| `workflow_run` | Adds `agent_id` (required, cascades with the Agent), filled from the workflow's Agent, and the nullable `title`. |
| `permissions` | Adds `workflow.manage`, granted in code to Organization Owners and Admins. |

`workflow_execution_scope_guard()` is replaced: on insert a run's Agent and its
initiating Membership must both belong to the workflow's Organization, and
`agent_id` joins the pins that cannot change afterwards. Workflows whose Agent
was deleted before the migration are kept as ordinary Organization workflows
without a default Agent, and their runs become readable again as runs on an
archived Agent.

The downgrade is lossy. A workflow gets one Agent back: its default Agent, else
the Agent of its latest run. Workflows with neither are deleted, runs made on any
other Agent are deleted, and creators, default Agents and run titles are dropped.

## AF-389 acceptance dependencies

PR [#326](https://github.com/aai-labs/agent-barn/pull/326) is merged into
staging. This local integration slice closes automatic replay of failed/expired
attempts and repeat trigger admission after restart. Live Agent-session execution,
OpenClaw stop/quiescence and run-read-policy coordination still need acceptance.
Callback/storage fencing does not prove tools stopped or that external writes are
safe to repeat. Artifact and run reads retain the current `agent.read` boundary.

## File workflow inputs and results

A saved input with `type: "file"` accepts exactly `{artifact_id, checksum}` at run
start. People select a READY artifact belonging to the Agent chosen for the run or upload through
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
checkpoint outputs. The trigger retrieves actual bytes into a fresh hidden
workspace directory (`.workflow-files-*`) using UUID filenames, checks each pinned
checksum, and supplies verified local paths to the step. Retrieval requests carry the attempt ID and must
find an active pin for that run; current initiator, Agent, generation and deadline
are checked before each new link and again after downloads before runtime start.
Download, integrity or admission failure prevents starting the session and parks
the run rather than silently substituting summaries. The final assembled prompt must fit 64,000 UTF-8 bytes and is checked before downloads. Up to four files are retrieved concurrently within a shared 120-second deadline; every manifest file remains required because the workflow has no per-step file selection. A failed or unavailable file therefore prevents that step from starting. Temporary inputs are removed when the trigger finishes and abandoned directories are cleaned at trigger startup. A directory deletion failure logs a warning and leaves that directory for a later startup to retry, while cleanup of other directories and trigger server startup continue;
the Agent running the step remains a shared filesystem/trust boundary, not a session sandbox.
Hidden temporary inputs follow the [file-sync exclusion rules](sync-provider/README.md#what-syncs):
the sync helper does not mirror them or offer provider edits to that transient path.
Already issued bearer URLs and bytes already read retain the existing artifact
revocation limitations.

Completion persists exact published output references in the accepted
checkpoint, with the legacy step output description when the version has one.
Every published file is downloadable, regardless of what the goal asked for. The Agent chooses whether the
requested deliverable needs files and reports unmet criteria if it cannot produce
or publish them. There is no author-selected file type or file-count completion
gate. Earlier files are available as inputs; they are not silently promoted to
final outputs. The service verifies published bytes, not whether a file's content
satisfies free-text criteria. `steps[].artifacts` exposes accepted checkpoint outputs;
`final_artifacts` contains only the successful last checkpoint's files and
`final_output_description` reflects the last step's legacy output description
and is null for versions saved without one. Failed/unfinished
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
