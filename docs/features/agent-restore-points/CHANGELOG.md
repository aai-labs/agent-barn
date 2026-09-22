# Agent Restore Points — change log

Status: Active
Epic: AF-292
Related context: [`../agents.md`](../agents.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md)

## Current state

- Delivered: server-side capture, list, read, restore, and delete of an Agent Restore Point, with
  reconcile-on-read resolving rows from live Job status, lifecycle guards on start and delete,
  and `agent.restore_point.*` Domain Events.
- In transition: nothing. The API surface is complete for Ticket 1 and safe to depend on.
- Next: Ticket 2 (reclaim stranded restore points and orphaned volumes). Ticket 3 — the Agent
  configuration page section and the opt-in replay of the captured configuration — is delivered
  on AF-298, which branches from this work and merges after it.
- Blockers: **Ticket 2 must ship in the same release as Ticket 1.** Ticket 1 resolves a row's
  status when someone reads it; a capture nobody ever reads keeps its row non-terminal until a
  read reclaims it, so restore points created and abandoned can hold a PVC indefinitely. The
  guards reconcile before evaluating, so this cannot make an Agent permanently undeletable, but
  it is a storage leak shipped alongside a storage feature.

## Changes

### 2026-09-21 — AF-298 — OpenClaw volumes with npm plugins could not be restored

- Fixed: an OpenClaw Agent that had ever installed an npm plugin produced an archive that
  could never be restored. Every managed npm install links the core into the plugin project
  from `/usr/local`, outside the volume. The capture Job runs the API image, where that path
  does not exist, so the link is dangling; `os.walk` classifies entries by following them, a
  dangling link fails `is_dir` and arrives among the files, and `tarfile` records it with its
  absolute target. `data_filter` then rejects that member and the restore fails after the
  safety-net capture has already run. The Agent volume is untouched — validation precedes the
  wipe — but the restore point is unusable. Capture now drops a link whose target leaves the
  volume and keeps everything else, including links that stay inside it, such as npm's own
  `.bin` shims. Hermes was never affected: nothing on its volume is a symlink.
- Fixed: the start script recreates the dropped link rather than reinstalling the plugin.
  `npm/` and `state/` have to be captured together — OpenClaw records an install in
  `state/openclaw.sqlite`, and restoring that record beside a missing tree leaves an install
  that cannot be repaired: it refuses the package with "no authoritative runtime child list",
  and `plugins registry --refresh`, `plugins uninstall` and `doctor --fix` do not clear it.
  Both come back together now, so only the link is missing, and recreating it needs no npm,
  no network and no registry.
- Fixed (API): both restore point provisioning handlers log the exception. The reason stored
  on the row is deliberately reduced to fixed copy, so the cluster's own account of a
  rejection — which field it refused — had no surviving record anywhere.
- Fixed: `migrations/env.py` passes `disable_existing_loggers=False`. The model imports at the
  top of that file create every `api.*` logger before `fileConfig` runs, so a process that
  applies migrations in-process — the test harness runs them against a live app — silenced
  application logging for the rest of its life. No log assertion could pass, and existing
  tests asserting that secrets stay out of the logs were passing against empty output.

- Superseded: the 2026-09-17 entry excluded OpenClaw's `npm` registry from archives and dropped
  every symlink an OpenClaw archive would carry. That left `state/` restored while the packages
  it records were gone, and left Hermes exposed to the same dangling-link failure. Archives now
  carry the tree and omit only the links that resolve outside the volume, for both runtimes.

### 2026-09-14 — AF-298 — Restore points in the Agent configuration page

- Added: a "Restore points" section between "Agent-owned override" and "Danger zone" on the
  Agent configuration page. It lists each restore point with its label, capture time, size,
  status, and a badge for system-created (`PRE_RESTORE`) entries; captures, restores, and
  deletes from there; and shows a failed entry's reason.
- Added: the list polls while any entry is non-terminal or owes configuration replay, and stops
  once both are resolved. The API
  resolves a row's status only when someone reads it, so the poll is not a convenience — it is
  what advances a capture.
- Added: each entry shows its captured configuration as a diff against the Agent's current one.
  The comparison is made on pin identity — template scope, key and version; skill id and version
  — never on the rendered label, because an Organization fork shares its platform lineage's key
  and restarts at v1, and two distinct Skill lineages may share a name and version. The current
  side is read from the active configuration version, which is the only read carrying the pin's
  scope; the Agent DTO reports only "shared" or "override".
- Added: the restore dialog offers an opt-in, off-by-default replay of the recorded pins. Both
  permissions are settled when the restore is requested — `agent.update` for the configuration
  beside the lifecycle permission for the volume — because the configuration is written later,
  by reconciliation, once the Job confirms the volume is back. The recorded configuration is
  validated before the Job starts, so one that can no longer be applied refuses the restore
  rather than costing the Agent its files first; the intent is stored on the restore point, and
  the selection is rebuilt on the server from the stored manifest so that what was checked
  before the Job is what is written after it. A restore that fails leaves the configuration
  untouched, and nothing depends on a browser staying open. When the configuration cannot be
  applied by then, the volume restore stands and the row records why it did not follow, with a
  `POST …/restore-points/{id}/configuration` to try again.
- Fixed (API): the replay intent survives an interruption. It is stored on the row and swept
  separately from the status, so a process that stops between marking the restore done and
  writing the configuration leaves work the next read finds — the row is terminal by then, and
  the non-terminal sweep would never look at it again.
- Fixed (API): two readers cannot both apply the same replay. The intent is re-read under the
  Agent's lifecycle lock and cleared in the same transaction as the pins and audit events. An
  interrupted transaction leaves it pending. Pending replay blocks start, delete, and further
  volume operations; start and delete reconcile before taking the lock replay also needs.
- Fixed (API): a restore that did not replace the volume clears the intent instead of applying
  the configuration, including when provisioning the Job fails. A failed safety-net capture returns the 
  row to `READY` because its archive is still good, which is not the same as the restore having happened.
- Fixed (API): the deferred write is attributed to whoever asked for the restore. It used to
  name whoever captured the restore point — often a different person, and the system for an
  automatic backup.
- Fixed (UI): the list keeps polling while a replay is owed, because reconciliation only runs on
  a read; and when the last one clears, the Agent detail and configuration reads are refreshed,
  so the model, skills, template and diff stop showing what they showed before the replay.
- Changed (API): `select_agent_template`'s validation moved into a shared `SelectionValidator`,
  so the check that runs before a restore and the write that runs after it cannot drift. The
  Agent service keeps its helpers as delegations, so no existing call site moved.
- Fixed (API): credentials are checked only for the Skills a request adds or re-pins. A Skill
  lineage records its *newest* version's requirements, so checking every assigned required Skill
  meant a credential added to a version the Agent does not use blocked an unrelated template
  switch.
- Added: restore is confirmed by typing the Agent's name into a destructive `ConfirmationDialog`
  that names what is replaced and says plainly that the runtime's session history rolls back
  with the volume while the conversation record here does not.
- Added: the list pages. System-created backups and failed captures occupy the list without
  counting against the cap, so without paging they could bury every manual entry — and a row
  that cannot be reached holds a volume that cannot be reclaimed from the UI.
- Changed: once the API accepts the restore, the dialog stops offering the destructive submit.
  Re-submitting it would conflict with the running Job, or — after that Job finishes and the row
  returns to `READY` — start a second restore nobody asked for. What remains is an
  acknowledgement and, when the replay failed, a configuration-only retry.
- Fixed (API): required-skill validation demanded that *every* entry in a template's requirement
  map be assigned at its pinned version, which made an "at least one of" group unsatisfiable —
  the unchosen alternative failed the version check before the group check was reached, and its
  credentials were demanded too. Presence is now checked first and per the group contract, and
  versions and providers only for what the Agent actually holds. The helper predates this work
  and is shared with override publish and draft save; routing replay through it is what exposed
  the failure, and no test covered a group through the selection path.
- Fixed (API): group version checking is delegated to `_validate_required_skill_versions`, the
  validator `update_agent` already uses, so the two write paths accept the same configurations. A
  group needs one member at the required version; a second member assigned at a later version is
  the caller's business. Checking every assigned member instead meant a configuration
  `update_agent` had accepted could not be replayed.
- Fixed (API): the selection path validated provider coverage only for template-required Skills,
  so a replay could reintroduce an optional Skill whose credential had since been removed. Every
  prospective assignment is now checked.
- Fixed (API): a selection that moved only skill pins left the Agent row clean, so its
  `onupdate` timestamp never advanced and a stale `expected_agent_updated_at` stayed acceptable.
  The revision is now advanced explicitly, which also serializes concurrent selections — the
  timestamp check runs under the row lock, while the prospective-state validation does not.
- Fixed (API): the selection payload accepted an explicit null `approval_mode` or `verbose_mode`
  and forwarded it to non-nullable columns. Both are now rejected as validation errors, matching
  the validators `AgentUpdate` already carries. Null keeps its meaning for `model` alone.
- Fixed (UI): capture stays disabled until a page of restore points has actually arrived. Before
  that the hook reports cap 0 and an empty list, which reads exactly like an Agent with room to
  spare — so an Agent at its cap was offered an enabled button for the length of the request, and
  indefinitely if that request failed.
- Fixed (UI): the dialog cannot be dismissed while a replay is in flight. Pending state spans the
  whole operation rather than its mutations — between reading the Agent and submitting the
  selection nothing is pending, and a dialog closed in that window unmounts before its outcome
  exists, so a failure would be reported into nothing.
- Fixed (UI): the configuration replay builds its request from a read of the Agent taken at that
  moment. The detail query neither polls nor refetches on focus, so a dialog left open holds a
  snapshot, and both the concurrency timestamp and the set of skills to remove are statements
  about the Agent's present state — a retry built from the snapshot would be refused as stale
  every time without ever becoming correct.
- Fixed (UI): the list showed each entry's creation time even once the archive existed. It now
  shows the capture time, falling back to the request time labelled "(requested)" while a
  capture is queued or running.
- Changed (API): `select_agent_template` accepts the skill pins and runtime settings that must
  hold with the selected template, validates a template's required skill pins against the
  assignments the Agent will end up with rather than the ones it has, and commits the pin, the
  skills and the settings in one transaction. Without this a replay could not work: applying a
  template and its skills as two requests has each half judged against the other's unwritten
  state, so a recorded template whose required skill pin differs from the Agent's present one
  was refused even though every recorded version still existed. A rejected selection now writes
  nothing, which is what removes the half-applied replay rather than reporting it.
- Changed: capture and restore are disabled with the reason in a tooltip — Agent running, work
  already in flight, the cap reached with the count named, or the entry not ready — rather than
  surfacing a `409`.
- Changed (API): the config manifest recorded only the model, approval mode, and verbose flag,
  so the diff Ticket 1 promised had nothing to compare and the replay nothing to re-apply. It
  now also records the template pin and the Agent's skill pins, at manifest `version` 2. The
  pin is recorded as `template_selection_type` (`platform`, `organization`, `override`) rather
  than the display pin type, because the display type collapses platform and organization
  templates into "shared" and a replay has to tell them apart. A `version` 1 row still parses
  and reports its missing pins as "Not recorded", which is not the same as empty.
- Changed (API): the restore point list reports `cap` and `manual_count`. The cap counts
  neither system-created backups nor failed captures while `total` counts both, so a client
  could not work out its remaining headroom from the page.
- Changed (UI): `ConfirmationDialog` takes `confirmDisabled`, which is what lets a typed-name
  check gate confirmation without a second dialog component.
- Documented: `docs/features/agents.md` gains Restore points in the configuration-page surface
  and records the configuration manifest and its versioning, the section's permission gates, the
  selection path's explicit scope and prospective-assignment validation, and the replay's
  all-or-nothing semantics. The epic log does not stand in for that.

### 2026-09-14 — AF-292 — Ticket 1 review fixes

- Changed: OpenClaw's archive excluded every `workspace/*.md` except `USER.md`, so an Agent's own
  markdown was never captured and a restore destroyed it. It now excludes exactly the seven files
  its ConfigMap regenerates, as Hermes already did.
- Changed: a restore Job is no longer retried (`backoff_limit` 0; capture keeps 1). A retry
  re-ran the safety-net capture against the already-wiped volume, overwriting the good backup.
- Changed: reconcile no longer fails a row whose Job does not exist yet. Rows are committed
  before their Job is created and reads take no lock, so a read in that window could fail a
  healthy capture and — on restore — delete the archive being restored from. Missing Jobs are
  now acted on only after a 60s grace window, mirroring the event reconciler; the restore's
  `job_name` is written in the same update as `RESTORING`.
- Changed: a failed restore is classified by which phase failed, and releases nothing when that
  cannot be established. Previously a restore killed by its time limit deleted a complete backup.
- Observed: on local k3d, a Job killed by `activeDeadlineSeconds` has its pod deleted outright,
  taking the exit code and logs with it; the Job's `DeadlineExceeded` condition survives and now
  drives a failure reason naming the timeout setting instead of pointing at logs that no longer
  exist.
- Observed: the Kubernetes Python client's `read_namespaced_pod_log` returns the Python repr
  rather than the text when a log body is valid JSON, and a bytes repr for multi-line bodies.
  Every successful capture prints exactly one JSON line, so `archive_bytes` and `file_count`
  would have been `null` in production. `read_job_logs` now reads the raw response body. Mock
  tests could not catch this; the new k3d cases do.
- Coverage: the acceptance criterion tying each exclusion to the line that regenerates it was
  never implemented and is now a test, evidenced from the start scripts, `init-openclaw.js`,
  `aai_cli_artifacts.py`, and the OpenClaw ConfigMap builder itself.

### 2026-09-10 — AF-292 — Ticket 1

- Delivered: `POST/GET …/agents/{id}/restore-points`, `GET/DELETE …/restore-points/{id}`, and
  `POST …/restore-points/{id}/restore`. Capture and restore run as Kubernetes Jobs on the API's
  own image against a stopped Agent.
- Changed: new `agent_restore_point` table, two enums, and a partial unique index
  (`a7c3e91d5b48`); new `api/domains/restore_points/` domain; `batch/v1` support and Job-log
  reads on `KubernetesClient`; `batch/jobs` and `pods/log` added to `k8s/agent-farm-user*.yaml`;
  `API_IMAGE` and four `RESTORE_POINT_*` settings wired through the chart; `agentbarn-api`
  chart `0.8.0` → `0.9.0`; `202` added to the status-code list in `guidelines/code.md`.
- Decision: the archive excludes credential material, boot-regenerated state, and the durable
  message spool, and retains each runtime's agent-owned `USER.md`. Restore performs its
  safety-net capture and its extraction in a single Job, because a `202` endpoint cannot wait
  for the first to finish and chaining two Jobs would add a state machine whose failure mode is
  an extraction that never starts.
- Decision: no new Permission keys — reads on `activity.read`, mutations on
  `agent.lifecycle.manage`.
- Observed: five defects in the original design were corrected during implementation — the
  status set could not represent an in-flight restore (added `RESTORING`); the retention cap
  would have blocked the Pre-Restore capture a restore itself creates; the `CASCADE` foreign key
  never fires because Agents are soft-deleted; restore point PVCs and Jobs are unreachable from
  `delete_agent`'s name-based teardown and are now found by label; and hostile archives were
  rejected only during extraction, i.e. after the wipe, which is now done during validation.
- Follow-up: Tickets 2 and 3. The end-to-end `make test-api-k8s` round trip against real volumes
  is written but has not been run against a disposable cluster with a rebuilt API image.
