# Agent Restore Points — change log

Status: Active
Epic: AF-292
Related context: [`../agents.md`](../agents.md), [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md), [`../rbac/IMPLEMENTATION-BRIEF.md`](../rbac/IMPLEMENTATION-BRIEF.md), [`../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md`](../../adr/2026-09-10-restore-points-use-tar-jobs-not-csi-snapshots.md)

## Current state

- Delivered: server-side capture, list, read, restore, and delete of an Agent Restore Point, with
  reconcile-on-read resolving rows from live Job status, lifecycle guards on start and delete,
  and `agent.restore_point.*` Domain Events.
- Delivered: reconciliation on a schedule (AF-297), so a row's status no longer depends on
  somebody reading it and restore point volumes no row owns are reclaimed.
- In transition: nothing. Tickets 1, 2 and 3 are complete.
- Next: nothing planned. Storage remains unmetered per Organization — the only bound is
  `RESTORE_POINT_MAX_PER_AGENT`, which is per Agent.
- Blockers: **no capture or restore has yet run end to end in a cluster with a rebuilt API
  image.** Every check so far is unit tests, mocked services, and the Kubernetes client against
  k3d. The `pods/log` grant is also unverified on staging and prod; without it a capture still
  runs but records no archive measurements and a generic failure reason. Watch the reconciler's
  first runs in staging before trusting the schedule — it is the one path here that deletes
  storage.

## Changes

### 2026-09-20 — AF-297 — Reclaim stranded restore points and orphaned volumes

- Changed: restore point PVCs and Jobs carry `agentbarn.io/restore-point-id`. Reclamation has to
  resolve a Kubernetes object back to the row that owns it, and `job_name` cannot serve: it is
  cleared when a row goes terminal, so every finished Job would look unowned. A restore Job is
  labelled with the restore point it restores *from*, matching the id its name already embeds,
  because one Job serves both that row and the Pre-Restore backup taken beside it.
- Note: objects created before this change carry no id label. The sweep refuses to delete what it
  cannot identify, so they are reported and left for one manual cleanup rather than guessed at.
  `docs/guidelines/operations.md` has the query and the order to delete in.
- Added: a `<release>-restore-point-reconciliation` CronJob on a 10-minute schedule, gated on
  `restorePoints.reconciliation.enabled` and modelled on the cost-sync template rather than the
  event reconciler's — this job talks to the Kubernetes API, so it needs the service account, the
  namespace and the mounted kubeconfig that the event reconciler does without. `agentbarn-api`
  chart `0.9.1` → `0.10.0`; `make reconcile-restore-points` runs one pass locally.
- Documented: the CronJob, its summary log line, the pre-`0.10.0` manual cleanup, and the three
  limits that keep the sweep conservative, in `operations.md`; the reconciliation pass and its
  label matching in `runtime-and-deployment.md`; and, in the RBAC brief, the narrow exception
  that lets scheduled background work query Agent-subordinate tables without an accessible-Agent
  join, with the three conditions it depends on.
- Added: `restore_points/constants.py`, and the claim the reconciler runs on. A restore point has
  no status to flip on claim, so the claim is `SELECT … FOR UPDATE SKIP LOCKED` over stale rows
  that bumps `updated_at` in the same transaction — which is what stops a concurrent run's
  staleness filter matching them. One claim covers both non-terminal rows and READY rows that
  still owe a configuration replay, because a second claim in the same run would find nothing the
  first had left.
- Added: `find_ready_rows_missing_volumes`, for the terminal rows the claim cannot reach — a READY
  row whose archive volume is gone is still offered for restore until something says otherwise.
  Its caller must establish that the volume listing succeeded, since an empty set matches
  everything.
- Moved: the 60-second pending grace from `service.py` to the new constants module, so the read
  path and the reconciler read one definition.
- Added: `reconcile_row(row, respect_grace=...)` and `apply_owed_replay(row)` on
  `RestorePointService`, the two seams the reconciler drives rather than restating what the read
  path already does. The read path keeps the grace window unchanged.
- Added: `restore_points/reconciliation.py` — a bounded pass that claims stale rows and resolves
  them from live Job status, applies any configuration replay they still owe, fails READY rows
  whose archive volume has gone, and deletes restore point Jobs and volumes no row owns. Bound by
  a batch size, a wall-clock budget, and a per-run deletion cap; wired through `@provider` and run
  as `python -c "… import main; main()"`, since `-m` re-imports the module under a second name and
  breaks the injector's Protocol bindings.
- Decision: the sweep destroys storage from a list-and-compare, so three things constrain it. An
  object younger than the minimum age is left alone, because it may belong to a row being
  provisioned right now. An object with no `restore-point-id` label is logged and never deleted,
  because it cannot be positively identified and guessing is worse than leaking. And an empty or
  failed volume listing fails no rows at all — an empty set matches every READY row, which is
  exactly the catastrophic case.
- Fixed: the reconciler deleted the archive of a healthy restore point. A READY row that still
  owed a configuration replay is claimed on purpose — that is how an owed replay is found, since
  it lives on a terminal row — but it was then put through the same resolution as a stranded
  operation. `job_name` is cleared when a restore completes, so that resolution saw a row with no
  Job, treated it as a capture that never produced one, and released its volume. The status write
  was correctly refused as terminal; the volume deletion ran anyway, so the row went on reporting
  READY with its archive gone until the missing-volume pass failed it. Resolution now skips
  terminal rows, and a capture releases its volume only when it is the caller that actually
  failed the row — either alone prevents it.
- Coverage: the defect survived because the reconciler's unit tests drive a fake service and the
  service's tests never run from a real claim, so nothing executed the claim and the real
  resolution together. There is now an integration test that runs `run_once` against the real
  service and repository.
- Added: `mark_ready_row_failed`, because `mark_failed` only transitions from non-terminal
  statuses and a READY row whose volume has gone is terminal — the existing method would have
  written nothing and the pass would have reported success while changing no row.
- Fixed: without `respect_grace`, the reconciliation pass would have resolved nothing. Claiming a
  row bumps its `updated_at`, which makes it look freshly committed to the 60-second grace that
  exists to protect a row whose Job has not been created yet — so every row the cron claimed
  would have been skipped as too young. The cron has already waited the longer staleness
  threshold to select the row at all.

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
