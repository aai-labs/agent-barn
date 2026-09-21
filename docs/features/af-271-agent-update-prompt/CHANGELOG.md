# AF-271 Agent update prompt — change log

Status: Active
Epic: AF-271
Related context: [`../agents.md`](../agents.md),
[`../agent-settings.md`](../agent-settings.md),
[`../../architecture/runtime-and-deployment.md`](../../architecture/runtime-and-deployment.md)

## Current state

- Delivered: a runtime configuration digest derived from the static closure of
  the Agent assembly code plus the runtime image references. It is computed and
  tested but not yet read, written, or exposed, so no runtime behaviour changes.
- In transition: nothing. The digest has no persisted counterpart until
  AF-271-02 adds `Agent.running_config_digest`, so nothing can compare against
  it yet.
- Next: AF-271-02 — persist the digest a pod started on.
- Blockers: none.

## Changes

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
