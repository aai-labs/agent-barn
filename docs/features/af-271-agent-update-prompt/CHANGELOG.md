# AF-271 Agent update prompt — change log

Status: Active
Epic: AF-271
Related context: [`../agents.md`](../agents.md),
[`../agent-settings.md`](../agent-settings.md),
[`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

## Current state

- Delivered: a runtime configuration digest derived from the static closure of
  the Agent assembly code plus the runtime image references, and
  `Agent.running_config_digest`, which records the digest a running pod was
  started on. Nothing reads the column yet, so no client behaviour changes.
- In transition: the column is written but not exposed. Agents already running
  when the migration lands keep the empty default until their next start, which
  is what makes them report an available update once AF-271-03 exposes the
  comparison.
- Next: AF-271-03 — expose `AgentRead.update_available`.
- Blockers: none.

## Changes

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
  the closure reaches 31 modules, 45 asset files and 212 definitions, silently
  omitting `skills.models.derive_tools_pointer`,
  `agent_settings.lookup.resolve_default_model`,
  `google_workspace_scopes.required_service_scopes`, `skills.files.DEFAULT_ENTRY_PATH`,
  `templates.slug.slugify`, the credential content schemas in `agents/models.py`,
  and `infrastructure.kubernetes.client`. A curated list is therefore not a
  maintainable option, and no version constant or digest is hand-maintained.
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
