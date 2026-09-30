# AF-271 Agent update prompt — change log

Status: Completed
Epic: AF-271
Related context: [`../agents.md`](../agents.md),
[`../agent-settings.md`](../agent-settings.md),
[`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

## Current state

- Delivered: the advisory update signal, end to end. A runtime configuration
  digest derived from the static closure of the Agent assembly code plus the
  runtime image references, `Agent.running_config_digest` recording what a
  running pod started on, `AgentRead.update_available` reporting when the two
  disagree, and a black Update control on the Agent page that runs the existing
  stop/start, explains itself on hover, and links to the release notes. Durable
  facts now live in [`../agents.md`](../agents.md) and
  [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md).
- In transition: **on the deploy that carries this epic, every already-running
  Agent reports an available update at once.** Those pods predate the record, so
  the report is accurate rather than a defect, and it clears per Agent on the
  next start. An operator fleet rebuild
  (`rebuild_running_agents_for_maintenance`) clears it for everyone.
- Next: nothing. The epic is complete.
- Blockers: none.

## Why this log is retained

Per [`../../guidelines/epics.md`](../../guidelines/epics.md), a completed log is
kept only when its migration or compatibility history stays useful. The one-time
fleet-wide prompt above is a live deployment concern, and the closure
measurement in AF-271-01 is the evidence for why the watched set must stay
computed — a future change proposing a hand-maintained list should read it
first. Delete this log once the fleet has turned over.

## Changes

### 2026-09-22 — AF-271-07

- Delivered: review fixes. The closure walk is now transitive *inside* each
  injected collaborator, not only across the methods the assembly path calls
  directly, so helpers reached one level deeper are covered.
- Finding: the walk previously stopped at the collaborator's entry method,
  missing `KubernetesClient._create_or_get`,
  `KubernetesClient._delete_ignoring_not_found` and
  `AgentSettingsLookupService.get_default_model`. Editing any of them changed
  what a pod starts on without moving the digest — an under-report, which
  contradicted the documented claim that the design only over-reports.
- Changed: `_assembly_methods` generalised to `_reachable_methods(methods, seed)`
  and reused for both `AgentService` and each collaborator class. Measured as
  strictly additive: +3 definitions, no new modules, nothing dropped.
- Changed: `_parse_cache` is released once `_STATIC_DIGEST` is computed,
  dropping retained memory after import from 19.6 MB to 1.1 MB in every API,
  worker, communications and CronJob process. The digest is byte-identical
  either way.
- Changed: the Update control no longer unmounts mid-restart. Stop writes the
  stopped Agent into the detail cache, where `update_available` is false, which
  previously destroyed the button and its pending state while the start was
  still provisioning. The component now owns its own visibility and stays
  mounted, showing `Updating…` for the whole window.
- Changed: `runtime-and-deployment.md` now splits known limits into
  under-reporting and over-reporting, and adds mutable image tags — the digest
  folds in the image reference, not its content, so rebuilding `:dev` does not
  move it.
- Follow-up, not addressed: the lifecycle menu holds a separate
  `useRestartAgent`, so it still offers `Start` during a restart and a second
  click fires a second start, which the lifecycle lock rejects with 409. The
  menu's own `Restart` has the same gap.

### 2026-09-22 — AF-271-06

- Delivered: the Update control now explains itself. Hovering it states that the
  Agent is running an older release and should be restarted, and a focusable
  icon link beside it opens the project's releases page in a new tab.
- Changed: UI only — `agent-update-button.tsx`, plus a page-object locator and
  three Playwright cases. No API, schema or deployment surface.
- Decision: the link is a separate control rather than an anchor inside the
  tooltip. Radix closes a tooltip when focus moves, so a link placed inside one
  is unreachable by keyboard; the tooltip explains and the link is a real
  focusable element.
- Coverage: `ui/tests/e2e/agent-update-button.spec.ts` — the hover copy, the
  link's `href`/`target`/`rel`, and the link sharing the button's visibility
  gate in both the no-update and no-permission cases.

### 2026-09-21 — AF-271-05

- Delivered: the runtime configuration digest is documented in
  [`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)
  — a new step 11 in the assembly list, a `Runtime configuration digest`
  subsection covering how the closure is derived, the two asset roots, the
  normalisation rules, and the five known limits, plus a source-map row.
- Changed: documentation only.
- Decision: the resolver's re-export and relative-import requirements are
  recorded in the architecture doc rather than left in commit history, because
  skipping either silently drops the runtime builders from the closure and the
  failure is invisible without a test.

### 2026-09-21 — AF-271-04

- Delivered: `AgentUpdateButton`, rendered in the Agent detail toolbar before
  the lifecycle control when the server reports `update_available` and the
  actor holds `agent.lifecycle.manage`. It reuses `useRestartAgent`, so the
  Update action and the existing Restart menu item are the same stop/start.
- Changed: UI only — `AgentSchema.updateAvailable`, one new component, one line
  in `agent-detail-page.tsx`, and Playwright page-object, fixture, and spec
  coverage. No API, schema, or deployment surface.
- Decision: the control reuses the existing `.af-btn-primary` black variant
  rather than introducing a style, and carries no confirmation dialog, matching
  the Restart menu item it duplicates.
- Decision: visibility is driven entirely by the server's `update_available`
  and `allowed_actions`, with no client-side re-derivation from Agent status,
  per the RBAC brief's backend/UI contract rule.
- Known gap: `AgentUpdateButton` and `AgentLifecycleMenu` each hold their own
  `useRestartAgent` instance, so a restart begun from one does not disable the
  other. Both paths are serialised by the Agent lifecycle lock, so the second
  click returns 409 rather than corrupting state.
- Coverage: `ui/tests/e2e/agent-update-button.spec.ts` — hidden when no update
  is available, hidden for a stopped Agent, hidden without lifecycle
  permission, visible beside the lifecycle control when available, and a click
  issuing stop then start.

### 2026-09-21 — AF-271-03

- Delivered: `AgentRead.update_available`, true only for a `RUNNING` Agent whose
  recorded digest differs from what the API would build now. It rides on the
  existing Agent read, so it inherits `require_visible` / `agent.read` and adds
  no endpoint and no authorization surface.
- Changed: API read contract (`AgentRead.update_available`) and
  [`../agents.md`](../agents.md) — a new invariant beside the model-inheritance
  rules, the Start and Stop flow descriptions, and a source-map row for
  `runtime_digest.py`.
- Decision: the signal stays advisory and narrow. It blocks nothing, changes no
  Agent behaviour, and clears on restart. It reports platform code and runtime
  images only, so `pending_model`, Template `source_update`, and the
  Skill-level `update_available` keep their own surfaces untouched.
- Decision: `STOPPED` and `ERROR` Agents always report `false`, whatever digest
  is stored. The field describes a live pod, and neither state has one.
- Coverage: `api/tests/integration/test_agents.py` — false after a start, true
  when the recorded digest differs, and false for both `STOPPED` and `ERROR`.

### 2026-09-21 — AF-271-02

- Delivered: `Agent.running_config_digest`, stamped in `_provision_and_start`
  beside `running_model` and cleared in `_stop_agent_unchecked`, so the Agent
  row records which code and images its live pod was actually built from.
- Changed: schema (`agent.running_config_digest`, `String(64)`,
  `server_default=""`) with migration `f2b9d4c7a610` off head `43ac1fbc7ff1`.
  No API, UI, or deployment surface.
- Decision: no backfill. An Agent running when the migration lands genuinely
  predates the tracking, so it keeps the empty default and reports an available
  update on the next read rather than being assumed current.
- Finding: `AgentRepository.save_with_lifecycle_event` copies an explicit
  allow-list of fields onto the locked row, so a lifecycle write that is not
  listed there is silently dropped. Both digest tests failed on the first run
  for exactly this reason; `running_config_digest` is now listed alongside
  `running_model`.
- Coverage: `api/tests/integration/test_agents.py` — start records the digest,
  stop clears it, and a start that fails before the runtime exists records
  nothing.

### 2026-09-21 — AF-271-01

- Delivered: `api/domains/agents/runtime_digest.py`, which identifies the code
  and images an Agent pod would be built from right now. Nothing imports it yet;
  the API behaves exactly as before.
- Changed: no schema, API, UI, or deployment surface. One new module and one new
  unit test.
- Decision: the watched set is **computed, not curated**. A hand-picked list was
  written first and measured against the real closure: it named 9 modules where
  the closure spans more than thirty, plus the asset roots, silently
  omitting `skills.models.derive_tools_pointer`,
  `agent_settings.lookup.resolve_default_model`,
  `google_workspace_scopes.required_service_scopes`, `skills.files.DEFAULT_ENTRY_PATH`,
  `templates.slug.slugify`, the credential content schemas in `agents/models.py`,
  and `infrastructure.kubernetes.client`. A curated list is therefore not a
  maintainable option, and no version constant or digest is hand-maintained.
  The digest module ends up inside its own closure, which is harmless: any
  change to the hashing algorithm invalidates every stored digest by
  construction, so excluding it would achieve nothing.
- Decision: the closure is built from `AgentService._provision_and_start` by
  following `self._method()` calls, `self.<collaborator>.<method>()` through the
  class-level annotations, and every free name to its defining module. It
  collects individual definitions rather than whole files, so editing an
  unrelated DTO in a shared module does not register while editing a reachable
  one does.
- Decision: runtime image identity comes from `Config.openclaw_image` and
  `Config.hermes_image`, not from `hermes-base/VERSION` or
  `openclaw-base/VERSION`. `api/Dockerfile` copies only `./api`, so those files
  do not exist in the API image.
- Decision: Python is normalised through `ast.dump` with docstrings stripped, so
  comments, blank lines, `ruff format` output and CRLF checkouts do not register
  while string literals — the policy text itself — do. The two asset roots
  (`domains/agents/scripts`, `domains/agents/aai_cli_skills/bundled`) are read as
  byte payload because the builders load them from disk, and are therefore
  compared byte-for-byte.
- Coverage: `api/tests/unit/test_agent_runtime_digest.py`. Beyond the
  normalisation and image-sensitivity cases, three assertions exist as
  regression guards for resolver defects found during implementation —
  collecting definitions with `ast.walk` instead of `tree.body` inflated the
  closure with 52 spurious entries, and failing to chase either the re-export
  barrel in `builders/__init__.py` or its relative `from .openclaw import` form
  dropped the runtime builders out of the closure entirely.
- Follow-up: AF-271-02 persists the digest; AF-271-03 exposes
  `AgentRead.update_available`; AF-271-04 adds the Agent page control;
  AF-271-05 documents the mechanism in the architecture guide and closes this
  log.
