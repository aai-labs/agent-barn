# AF-108 ← main merge plan

Branch: `AF-108-hermes-agents-support`
Target: merge `main` into `AF-108-hermes-agents-support`
Merge base: `5dfe8f1`

## Context

While AF-108 was in progress, three Jira efforts landed on `main`:

- **AF-114** — helmfile/single-command deploy (infra-only)
- **Agent secrets vault** (commit `c420417`) — encrypted per-provider integration secrets table + UI step
- **aai-cli injection** (commits `5d3a0a1`, `148418b`, `84e5ee3`) — bake aai-cli tool into the openclaw image, inject config.toml/setup.sh/skills.json via the agent ConfigMap, and seed `agent_skill` rows on agent creation

These changes touch almost every file AF-108 also touched. The merge is non-trivial because:

1. AF-108 **renamed** `api/domains/agents/builders.py` → `api/domains/agents/builders/openclaw.py` and split it into a package. `main` continued modifying the file at the old path.
2. AF-108 **extracted** embedded JS/SH string literals out of `builders.py` into `api/domains/agents/scripts/openclaw/*.{js,sh}`. `main`'s modifications were applied to the string literals, not the extracted files.
3. Both sides added a new alembic migration with the same `down_revision` (`23b02ff828ac`) → migration chain divergence.
4. Both sides redesigned overlapping wizard steps in the hire UI.

Main is the source of truth. We incorporate everything from main and layer our AF-108 changes on top.

## High-level steps

1. Roll back the AF-108 migration in the local DB (`make rollback`).
2. Merge `main` into the branch (`git merge main`).
3. Resolve conflicts per the file-by-file plan below.
4. Re-point the AF-108 migration's `down_revision` to the new main head.
5. Run `make migrate`, lints, unit + integration tests.
6. Smoke-test the hire dialog end-to-end (OpenClaw + Hermes paths).
7. Commit the merge.

## File classification

### A. Clean adds from main (no conflict, accept as-is)

These files only exist on main; they will appear in the working tree after the merge:

- `api/domains/agents/aai_cli_artifacts.py` — build_config_toml / build_env / build_setup_sh / provider_to_secret_name_map
- `api/domains/agents/aai_cli_skills/` (6 files) — skill doc loader, manifest builder, predefined skill docs
- `api/migrations/versions/f3a91c7b2e58_add_agent_secret_and_skill_tables.py`
- `api/tests/unit/test_aai_cli_artifacts.py`
- `api/tests/unit/test_aai_cli_skills.py`
- `api/tests/unit/test_agent_secrets.py`
- `helm/agentfarm-api/templates/kubeconfig-secret.yaml`
- `helm/agentfarm-api/templates/registry-secret.yaml`
- `helm/agentfarm-api/templates/secret.yaml`
- `helm/litellm/templates/secret.yaml`
- `helm/postgres/templates/secret.yaml`
- `ui/src/features/agents/integrations.ts`

### B. Clean adds from AF-108 (no conflict, keep as-is)

These only exist on the branch; main is untouched:

- `agent_plans/AF_108_plan.md`, `AF_108_implementation_notes.md`
- `api/domains/agents/builders/__init__.py`, `common.py`, `hermes.py`
- `api/domains/agents/scripts/hermes/` (entire tree)
- `api/domains/agents/scripts/openclaw/healthz-server.js`, `init-openclaw.js`, `start.sh`
- `api/domains/conversations/hermes_parser.py`
- `api/migrations/versions/c1d2e3f4a5b6_add_agent_type_to_agent.py`
- `api/tests/unit/test_hermes_builders.py`

### C. Files touched only by main (accept main's version)

These are not contested — AF-108 never touched them:

- `.github/workflows/deploy.yml`, `openclaw-base.yml`
- `.gitignore`
- `api/Dockerfile`, `api/VERSION`, `ui/VERSION`
- `api/migrations/env.py` — main added `import api.domains.agents.models` and `import api.domains.conversations.models` (AF-108 needs these too — keep main's version)
- `api/domains/agents/repository.py` — main added secret/skill repo methods; AF-108 didn't touch this file but needs to *use* those methods (see service.py merge)
- `helm/agentfarm-ui/templates/deployment.yaml`, `helm/agentfarm-ui/values.yaml`
- `helm/litellm/values.yaml`, `helm/postgres/values.yaml`
- `helmfile.yaml`
- `openclaw-base/Dockerfile`, `openclaw-base/VERSION`
- `ui/tests/e2e/hire-dialog.spec.ts`

### D. Contested files — manual resolution required

The following files are modified on both sides and need conflict resolution:

| File | Conflict type |
|---|---|
| `api/domains/agents/builders.py` (rename) ↔ `builders/openclaw.py` | Rename + modify |
| `api/domains/agents/defaults.py` | Both rewrote text content |
| `api/domains/agents/models.py` | Both added classes; one side added field to `Agent` |
| `api/domains/agents/service.py` | Both heavily modified `start_agent`, `create_agent`, imports |
| `api/core/config.py` | AF-108 added `hermes_image` field |
| `api/pyproject.toml`, `api/uv.lock` | AF-108 added deps (likely) |
| `api/tests/integration/test_agents.py` | AF-108 added Hermes tests (328 line delta) |
| `api/tests/steps/agent.py` | AF-108 added `agent_type` param |
| `helm/agentfarm-api/templates/deployment.yaml` | Both touched envFrom/secrets wiring |
| `helm/agentfarm-api/values.yaml` | Main consolidated values, AF-108 added `hermesImage` |
| `ui/src/features/agents/components/hire-dialog-steps.tsx` | Main added `IntegrationsStep`; AF-108 added `AgentTypeStep` |
| `ui/src/features/agents/components/hire-dialog.tsx` | Both restructured `getSteps` / step orchestration |
| `ui/src/features/agents/hooks/use-create-agent.ts` | Main added `secrets` field; AF-108 added `agentType` |
| `ui/src/features/agents/schemas.ts` | Main added `AgentSecretReadSchema`; AF-108 added `agentType` |

## File-by-file resolution plan

### D1. `api/domains/agents/builders.py` (rename → `builders/openclaw.py`)

**Situation**: git detected ~52% similarity rename. The conflict will manifest as both files present, or as rename/modify. Either way we keep the package structure (`builders/`) and port main's three additions into `builders/openclaw.py`:

1. `build_config_map(...)` gains three optional kwargs:
   - `aai_cli_config_toml: str | None = None`
   - `aai_cli_setup_sh: str | None = None`
   - `skills_json: str | None = None`

   In the function body, when each is non-None, write `aai-cli-config.toml`, `aai-cli-setup.sh`, and `skills.json` into the ConfigMap `data`.

2. `scripts/openclaw/start.sh` gets the aai-cli setup hook appended:
   ```sh
   if [ -f /app/config/aai-cli-setup.sh ]; then
     sh /app/config/aai-cli-setup.sh || echo "[aai-cli] setup failed; continuing"
   fi
   ```
   (Place it before the openclaw start command — match the position from main's diff.)

3. `scripts/openclaw/init-openclaw.js` gets the skills-manifest reconstruction block from main (~17 lines that read `skills.json` from `/app/config` and write each entry under `WORKSPACE_DIR/skills/`).

`builders/hermes.py` is untouched by the merge — it stays exactly as AF-108 wrote it. (Hermes aai-cli wiring is the follow-up commit, not the merge.)

**After resolution**: delete the merged `builders.py` if it survives the rename — only `builders/` package should remain.

### D2. `api/domains/agents/defaults.py`

Both sides rewrote the constants. Inspect the two versions:
- Main: kept the original short comment-style defaults but added `AAI_CLI_TOOLS_POINTER` constant that gets appended to every agent's `tools_md`.
- AF-108: rewrote all defaults to be long-form, instructional Markdown (USER.md / TOOLS.md / AGENTS.md / BOOT.md / HEARTBEAT.md).

**Decision**: keep AF-108's long-form defaults (they're the intended UX) **and** keep main's `AAI_CLI_TOOLS_POINTER` constant. Re-add `AAI_CLI_TOOLS_POINTER` to the exports so `service.py` can append it to `tools_md` only for OpenClaw agents in this merge. (Hermes will get the same treatment in the follow-up commit; see "Follow-up" section below.)

### D3. `api/domains/agents/models.py`

Both sides added classes; they don't collide semantically — accept both sets:

- Keep main's adds: `SecretProvider`, `SkillSource`, `SecretContent` + 8 per-provider content classes, `PROVIDER_DISPLAY_NAMES`, `PROVIDER_CONTENT_MODELS`, `validate_content`, `encrypt_content`, `decrypt_content`, `AgentSecret`, `AgentSkill`, `AgentSecretCreate`, `AgentSecretRead`.
- Keep AF-108's adds: `AgentType` enum, `agent_type` field on `Agent`, `AgentCreate`, `AgentRead`, the `validate_platform_credentials` validator's Hermes-rejects-Teams check.
- Keep `secrets: list[AgentSecretCreate]` on `AgentCreate` and `secrets: list[AgentSecretRead]` on `AgentRead` (main's behaviour) — AF-108 didn't intend to remove them, it just didn't have them yet.
- Keep the `validate_unique_secret_providers` validator on `AgentCreate`.

### D4. `api/domains/agents/service.py`

This is the heaviest merge. Strategy: **start from main, layer AF-108 changes on top.**

Imports:
- Keep main's `from api.domains.agents.aai_cli_artifacts import ...` and `from api.domains.agents.aai_cli_skills import ...`.
- Keep main's `from api.domains.agents.defaults import AAI_CLI_TOOLS_POINTER, ...` (rebuilt in D2).
- Add AF-108's `from api.domains.agents.builders import build_hermes_config, build_hermes_config_map, build_hermes_deployment, build_secret_hermes_slack` (alongside the existing openclaw builders).
- Add AF-108's `from api.domains.agents.models import AgentType`.
- Keep `import secrets` (AF-108) — needed for `secrets.token_urlsafe` used by Hermes api_server_key.

`_build_agent_read`:
- Keep main's `secrets: list[AgentSecret] | None = None` parameter and `secrets_read` building.
- Add AF-108's `agent_type=agent.agent_type` to the `AgentRead(...)` constructor.

`_get_agent_read`:
- Keep main's `secrets = self.repository.get_secrets_for_agent(agent.id)` call.

`create_agent`:
- Keep main's secrets persistence loop verbatim (it's payload-driven — Hermes hires that submit no secrets simply iterate an empty list).
- Keep `self.repository.save_skills(load_aai_cli_skills(agent.id))` **gated on `agent.agent_type == AgentType.OPENCLAW`** for the merge. The follow-up commit removes the gate.
- Keep `data.tools_md = (data.tools_md or DEFAULT_TOOLS_MD) + AAI_CLI_TOOLS_POINTER` **gated on `data.agent_type == AgentType.OPENCLAW`**.
- Pass `agent_type=data.agent_type` when constructing the `Agent`.

`list_agents`:
- Keep main's `secrets_by_agent` fetching and pass-through to `_build_agent_read`.

`start_agent`:
- Outer structure: keep main's Slack/Teams platform branch, but **inside the Slack branch**, add AF-108's `if agent.agent_type == AgentType.HERMES:` sub-branch that builds the Hermes config/secret/deployment using `build_hermes_*` and the dedicated `build_secret_hermes_slack`.
- The aai-cli artifact block (decrypt secrets, `build_config_toml`, `build_setup_sh`, `build_env`, `build_skills_manifest`) and the `aai_cli_config_toml=`, `aai_cli_setup_sh=`, `skills_json=` arguments to `build_config_map` apply **only to OpenClaw** in this merge. Skip entirely for Hermes (Hermes uses its own `build_hermes_config_map` which doesn't take those args).
- The `secret.string_data.update(build_env(store))` line stays inside the OpenClaw branch only.
- For Hermes, build/create the resources directly without merging into the OpenClaw artifact pipeline.

`update_agent`, `stop_agent`, `delete_agent`: no AF-108-specific changes; accept main's version.

### D5. `api/core/config.py`

Trivial — add `hermes_image: str = ""` to `Config`. Single-line addition.

### D6. `api/pyproject.toml`, `api/uv.lock`

AF-108 added `pyyaml` (used by `build_hermes_config` for YAML emission). Keep AF-108's pyproject change; **regenerate the lock** with `cd api && uv lock` after merge to reconcile any main-side dep updates.

### D7. `api/tests/integration/test_agents.py`

Main didn't touch this file (per the file-status diff — only AF-108 modified it). Keep AF-108's version verbatim. **Verify after merge**: run `make test-api` and confirm new Hermes tests still pass; if main added new aai-cli-related integration tests they'll arrive via the new test files (`test_agent_secrets.py`, etc.) without conflict.

### D8. `api/tests/steps/agent.py`

Three-line addition (import `AgentType`, add `agent_type` kwarg, pass it to `Agent(...)`). Accept AF-108's version.

### D9. `helm/agentfarm-api/templates/deployment.yaml`

Inspect both diffs. AF-108 likely added `HERMES_IMAGE` env wiring; main added secret-mount changes from AF-114. **Manual resolution**: keep main's secret/env structure as the base, append AF-108's `HERMES_IMAGE` env var sourced from the new values.yaml field.

### D10. `helm/agentfarm-api/values.yaml`

Main restructured the file substantially (consolidated registry prefix into image repositories, removed inline `dbConnectionUrl` etc. in favour of pre-existing secrets). AF-108 added `hermesImage:` block.

**Resolution**: start from main; add AF-108's `hermesImage:` block with the prefixed repository name once we have the registry path. Default `hermesImage.repository: nousresearch/hermes-agent` (current AF-108 default) — AF-123 will swap this to `registry.k8s.aai-labs.com/agentfarm-hermes-base` once the custom image is built.

### D11. `ui/src/features/agents/components/hire-dialog-steps.tsx`

Both sides modified the `WizardStep` union and added a step component:
- Main added `"integrations"` and `IntegrationsStep`.
- AF-108 added `"agent-type"` and `AgentTypeStep`.

**Resolution**: keep both. Final `WizardStep` union: `"role" | "agent-type" | "platform-choice" | "slack-choice" | "bot-builder" | "slack-tokens" | "teams-bot-builder" | "teams-credentials" | "details" | "integrations"`. Both component functions stay.

### D12. `ui/src/features/agents/components/hire-dialog.tsx`

The wizard step orchestration needs the merge logic:

- Hermes path: `role → agent-type → slack-choice → [bot-builder →] slack-tokens → details` (no integrations — Hermes aai-cli is the follow-up commit).
- OpenClaw + Slack: `role → agent-type → platform-choice → slack-choice → [bot-builder →] slack-tokens → details → integrations`.
- OpenClaw + Teams: `role → agent-type → platform-choice → teams-credentials → teams-bot-builder → details → integrations`.

`getSteps` keeps AF-108's signature `(agentType, platform, setupNewBot)` and appends `"integrations"` only when `agentType === "openclaw"`. The `stepTitle` switch keeps both `"agent-type"` and `"integrations"` cases. `startHiring` passes both `agentType` and `secrets`.

### D13. `ui/src/features/agents/hooks/use-create-agent.ts`

Trivial — keep both fields (`agentType?` from AF-108, `secrets?` from main).

### D14. `ui/src/features/agents/schemas.ts`

Trivial — keep both adds (`AgentSecretReadSchema` from main, `agentType` field on `AgentSchema` from AF-108).

## Migration chain fix

After the merge, two migrations both claim `down_revision = "23b02ff828ac"`:

- `c1d2e3f4a5b6_add_agent_type_to_agent.py` (AF-108)
- `f3a91c7b2e58_add_agent_secret_and_skill_tables.py` (main)

**Action**: rebase AF-108's migration on top of main's. Edit `c1d2e3f4a5b6_add_agent_type_to_agent.py`:

```python
down_revision: Union[str, None] = "f3a91c7b2e58"
```

Resulting linear chain: `... → 23b02ff828ac → f3a91c7b2e58 → c1d2e3f4a5b6`.

The branch's local DB must first be rolled back (`make rollback`) so `alembic_version` doesn't reference the now-rebased AF-108 migration with the old parent.

## Sequence of git commands

```bash
# 1. Pre-merge: roll back the AF-108 migration in dev DB
make rollback

# 2. Sync main and start merge
git fetch origin
git checkout AF-108-hermes-agents-support
git merge main
# Expect conflicts in the files listed in section D

# 3. Resolve conflicts file-by-file per section D, then:
git add <resolved files>

# 4. Fix migration chain BEFORE committing the merge
$EDITOR api/migrations/versions/c1d2e3f4a5b6_add_agent_type_to_agent.py
# change down_revision to "f3a91c7b2e58"
git add api/migrations/versions/c1d2e3f4a5b6_add_agent_type_to_agent.py

# 5. Regenerate lock if pyproject changed
cd api && uv lock && cd ..
git add api/uv.lock

# 6. Verify everything compiles & migrates
make migrate
make check    # lint+format gate
make test-api
make test-ui  # if it exists

# 7. Manually smoke-test the hire dialog
make dev-api & make dev-ui &
# - OpenClaw Slack path with integrations
# - OpenClaw Teams path with integrations
# - Hermes Slack path (verify NO integrations step appears)

# 8. Commit
git commit
```

## Verification checklist

Work through these in order. Each section gates the next — don't smoke-test the UI before the migrations are clean, etc.

### 1. Merge hygiene (no conflict markers, no orphans)

- [ ] `git status` is clean after merge commit (no `UU` / `AA` paths)
- [ ] `grep -rn '<<<<<<<\|=======\|>>>>>>>' --include='*.py' --include='*.ts' --include='*.tsx' --include='*.yaml' --include='*.sh' --include='*.js'` returns nothing
- [ ] `api/domains/agents/builders.py` does **not** exist (deleted after the rename); only `api/domains/agents/builders/` package remains
- [ ] `api/domains/agents/builders/__init__.py` exports both openclaw and hermes symbols (the AF-108 `__all__` list)
- [ ] No `unused import` warnings in service.py (e.g., dangling `AgentSecret` / `AAI_CLI_TOOLS_POINTER` imports if a gate was missed)
- [ ] `git log --oneline -1` shows the merge commit with both parent SHAs (`git log --merges -1 --format=%P` returns two)

### 2. Migration chain

- [ ] `cd api && uv run python -m alembic heads` prints exactly one revision: `c1d2e3f4a5b6 (head)`
- [ ] `cd api && uv run python -m alembic history` shows the linear order `... → 23b02ff828ac → f3a91c7b2e58 → c1d2e3f4a5b6` (no branches)
- [ ] `c1d2e3f4a5b6_add_agent_type_to_agent.py` has `down_revision = "f3a91c7b2e58"`
- [ ] `f3a91c7b2e58_add_agent_secret_and_skill_tables.py` still has `down_revision = "23b02ff828ac"` (unchanged)
- [ ] `make migrate` succeeds against a freshly-rolled-back DB
- [ ] `make rollback` (downgrade `c1d2e3f4a5b6` → `f3a91c7b2e58`) succeeds
- [ ] `make rollback` again (→ `23b02ff828ac`) succeeds
- [ ] `make migrate` after the two rollbacks succeeds and reapplies both new migrations
- [ ] `cd api && uv run python -m alembic check` reports no pending model/DB drift (no autogen would emit changes)
- [ ] In DB after `make migrate`:
  - [ ] `\d agent` shows `agent_type varchar(20) NOT NULL DEFAULT 'openclaw'` with check constraint `ck_agent_agent_type`
  - [ ] `\d agent_secret` exists with the unique constraint and provider check
  - [ ] `\d agent_skill` exists with the unique constraint and source check
  - [ ] Any pre-existing agent rows have `agent_type='openclaw'` (server default backfilled them)

### 3. Static analysis & build

- [ ] `make check` passes (lint + format gate)
- [ ] `cd api && uv lock --check` reports the lock is consistent with pyproject (or regenerate via `uv lock`)
- [ ] `cd api && uv run ruff check .` clean
- [ ] `cd api && uv run ty check` (or whichever type checker the project uses) clean
- [ ] `cd ui && pnpm typecheck` (or equivalent) clean
- [ ] `cd ui && pnpm lint` clean
- [ ] `cd ui && pnpm build` succeeds

### 4. Unit tests

- [ ] `cd api && uv run pytest tests/unit -q` all green
- [ ] `tests/unit/test_aai_cli_artifacts.py` (from main) passes — confirms aai-cli config builders unchanged
- [ ] `tests/unit/test_aai_cli_skills.py` (from main) passes
- [ ] `tests/unit/test_agent_secrets.py` (from main) passes
- [ ] `tests/unit/test_hermes_builders.py` (from AF-108) passes — confirms Hermes builders untouched
- [ ] No new test-collection warnings (missing fixtures, import errors)

### 5. Integration tests

- [ ] `cd api && uv run pytest tests/integration -q` all green
- [ ] `tests/integration/test_agents.py` Hermes cases (added by AF-108) all pass
- [ ] `tests/integration/test_agents.py` OpenClaw cases all pass (no regressions from agent_type field)
- [ ] `tests/steps/agent.py` step helper accepts `agent_type` kwarg without breaking existing callers (defaults to `OPENCLAW`)

### 6. Models, schemas, validation

- [ ] `AgentType` enum present in `api/domains/agents/models.py`, values `OPENCLAW = "openclaw"`, `HERMES = "hermes"`
- [ ] `Agent.agent_type` field exists with `AgentPlatform` default behavior preserved
- [ ] `AgentRead.agent_type` returned on `/api/v1/agents/{id}` (curl one)
- [ ] `AgentRead.secrets` still returned (curl an OpenClaw agent created with secrets)
- [ ] `AgentCreate.secrets` field still accepted and persisted
- [ ] `AgentCreate.validate_platform_credentials` rejects `agent_type=hermes` + `platform=teams` (POST returns 422)
- [ ] `SecretProvider`, `AgentSecret`, `AgentSkill`, all eight `*Content` classes importable from `api.domains.agents.models`

### 7. Builders & scripts

- [ ] `from api.domains.agents.builders import build_config_map, build_hermes_config_map, build_secret_hermes_slack` works
- [ ] `build_config_map` signature includes `aai_cli_config_toml`, `aai_cli_setup_sh`, `skills_json` kwargs (all default `None`)
- [ ] `build_hermes_config_map` signature does **not** include those kwargs (Hermes aai-cli is the follow-up)
- [ ] `api/domains/agents/scripts/openclaw/start.sh` includes the `if [ -f /app/config/aai-cli-setup.sh ]` block
- [ ] `api/domains/agents/scripts/openclaw/init-openclaw.js` includes the `SKILLS_MANIFEST` reconstruction block
- [ ] `api/domains/agents/scripts/hermes/start.sh` is byte-identical to the AF-108 version (`git diff HEAD~1..HEAD -- scripts/hermes/start.sh` empty for the merge commit's changes to that file)

### 8. Service layer behavior

- [ ] `service.create_agent` with `agent_type=OPENCLAW`: template `tools_md` has `AAI_CLI_TOOLS_POINTER` appended (assert in test or check DB)
- [ ] `service.create_agent` with `agent_type=HERMES`: template `tools_md` does **not** include the pointer
- [ ] `service.create_agent` with secrets on an OpenClaw hire: rows appear in `agent_secret`
- [ ] `service.create_agent` with secrets on a Hermes hire: rows still get persisted (loop is unconditional) — confirm in DB
- [ ] `service.create_agent` for OpenClaw: skill rows appear in `agent_skill`
- [ ] `service.create_agent` for Hermes: skill rows do **not** appear
- [ ] `service.start_agent` for OpenClaw: ConfigMap contains `aai-cli-config.toml`, `aai-cli-setup.sh`, `skills.json`
- [ ] `service.start_agent` for Hermes: ConfigMap does **not** contain those keys
- [ ] `service.start_agent` for Hermes: Secret has Hermes-specific env vars (`API_SERVER_KEY`, `SLACK_HOME_CHANNEL`, etc.), no `AAI_SECRET_*`
- [ ] `service.start_agent` for OpenClaw with secrets: Secret has `AAI_SECRET_*` env vars
- [ ] `service.list_agents` returns `agent_type` and `secrets` arrays for every row

### 9. Config & helm

- [ ] `api/core/config.py:Config.hermes_image` field present with `""` default
- [ ] `helm/agentfarm-api/values.yaml` has `hermesImage:` block with `repository` and `tag`
- [ ] `helm/agentfarm-api/templates/deployment.yaml` wires `HERMES_IMAGE` env from `.Values.hermesImage`
- [ ] `helm/agentfarm-api/templates/deployment.yaml` still wires the AF-114-added secret refs (kubeconfig, registry, etc.) — no accidental loss
- [ ] `helm/agentfarm-api/templates/kubeconfig-secret.yaml`, `registry-secret.yaml`, `secret.yaml` all present
- [ ] `helm/litellm/templates/secret.yaml`, `helm/postgres/templates/secret.yaml` present
- [ ] `helmfile.yaml` matches main's version
- [ ] `helm template helm/agentfarm-api/ -f helm/agentfarm-api/values.yaml` renders without errors

### 10. UI wizard end-to-end (manual)

Run `make dev-api & make dev-ui &` and use a real browser.

- [ ] Open the Hire dialog — defaults: agent type `Hermes`, platform implicitly Slack
- [ ] **Hermes + Slack (new bot) path**: steps shown are `role → agent-type → slack-choice → bot-builder → slack-tokens → details` — **no Integrations step**, no platform-choice step
- [ ] **Hermes + Slack (existing bot) path**: steps shown are `role → agent-type → slack-choice → slack-tokens → details`
- [ ] Switching from Hermes to OpenClaw on the agent-type step exposes the `platform-choice` step on Continue
- [ ] **OpenClaw + Slack (existing bot)**: `role → agent-type → platform-choice → slack-choice → slack-tokens → details → integrations`
- [ ] **OpenClaw + Slack (new bot)**: includes `bot-builder` between `slack-choice` and `slack-tokens`
- [ ] **OpenClaw + Teams**: `role → agent-type → platform-choice → teams-credentials → teams-bot-builder → details → integrations`
- [ ] Selecting Teams while Hermes is the agent type is impossible (or platform-choice doesn't appear)
- [ ] Integrations step renders all 8 providers (GitHub, Jira, Confluence, Bitbucket, Gmail, Google Calendar, Zoho Mail, Zoho Calendar)
- [ ] Adding an integration, then leaving a required field blank, disables the final Hire button (`hasIncompleteIntegration`)
- [ ] Step ordinal counter (`step N of M`) shows correct counts for each flow
- [ ] Back button traverses the same step sequence in reverse

### 11. Pod runtime smoke tests (k8s)

For each path, hire the agent through the UI and watch the pod come up:

- [ ] **OpenClaw + Slack hire** with one GitHub secret added:
  - [ ] Pod reaches `Running`
  - [ ] `kubectl exec -n agent-farm <pod> -- ls /app/config` shows `aai-cli-config.toml`, `aai-cli-setup.sh`, `skills.json`, `init-openclaw.js`, `start.sh`
  - [ ] `/home/node/.config/aai-cli/config.toml` exists with the `[profiles.github-work]` block
  - [ ] `aai-cli secrets list` (inside the pod) shows `github.token` set
  - [ ] `/home/node/.openclaw/workspace/skills/aai-cli/aai-cli_skill.md` exists
  - [ ] `TOOLS.md` ends with the `AAI_CLI_TOOLS_POINTER` text
  - [ ] Send a Slack DM/mention — agent responds
  - [ ] After ~30s, `conversation` and `tool_call` rows for this agent appear in DB
- [ ] **OpenClaw + Teams hire**:
  - [ ] Pod reaches `Running`
  - [ ] aai-cli artifacts present (same as above)
  - [ ] Send a Teams message — agent responds
- [ ] **Hermes + Slack hire** with no integrations added:
  - [ ] Pod reaches `Running`
  - [ ] `kubectl exec -n agent-farm <pod> -- ls /app/config` does **not** show `aai-cli-config.toml`, `aai-cli-setup.sh`, or `skills.json`
  - [ ] No `AAI_SECRET_*` env vars in the pod (`kubectl exec ... -- env | grep AAI_SECRET` empty)
  - [ ] `TOOLS.md` does **not** include the `AAI_CLI_TOOLS_POINTER` text
  - [ ] Send a Slack mention — Hermes agent responds
  - [ ] After ~30s, `conversation` and `tool_call` rows for this agent appear in DB (via the kubectl-exec sync path in `hermes_parser.py`)
- [ ] **Stop & restart** for each runtime:
  - [ ] `POST /api/v1/agents/{id}/stop` triggers `conversation_sync_service.sync_all_channels` and `sync_service.sync_agent` before deleting the deployment (check logs)
  - [ ] `POST /api/v1/agents/{id}/start` brings the pod back; state preserved

### 12. Regression sweep

- [ ] Existing OpenClaw agents (created pre-merge) still load in the UI (their `agent_type` defaults to `openclaw`)
- [ ] Existing OpenClaw agents can still be started/stopped after the merge
- [ ] No 500s on `GET /api/v1/agents` (the list endpoint runs through `_build_agent_read` for every row — verify it handles missing `agent_secret` rows for legacy agents)
- [ ] `POST /api/v1/agents/{id}/pair` still works (no changes expected, but it lives next to the touched code)
- [ ] `POST /api/v1/webhooks/teams/{id}/messages` still routes to OpenClaw Teams agents
- [ ] `make test` (full suite) still green

### 13. Final commit hygiene

- [ ] Merge commit message follows convention (`merge main into AF-108-hermes-agents-support` or the project's preferred wording — present tense per CLAUDE.md)
- [ ] No co-author lines in the merge commit (per CLAUDE.md)
- [ ] Branch is pushed: `git push origin AF-108-hermes-agents-support`
- [ ] PR diff against main reviewed for surprises before merging

## Risk inventory

- **Builders rename collision**: git's rename detection may surface as a "deleted by them, modified by us" conflict on `builders.py`. If so, resolve by deleting `builders.py` (we have the package) and manually porting the diff into `builders/openclaw.py` + `scripts/openclaw/*`.
- **`alembic_postgresql_enum` autogen for AgentType**: main's migration env.py is in use; ensure that re-applying our migration with the new parent doesn't autogenerate a no-op enum migration on top.
- **`agent_type` column default**: our migration sets `server_default="openclaw"`, so existing rows backfill fine after the merge.
- **Secrets exposed in Hermes pod**: gating the aai-cli injection on `agent_type == OPENCLAW` in `start_agent` keeps DB-stored secrets from leaking into Hermes pod env. **Don't skip that gate in the merge** — remove it deliberately in the follow-up commit.
- **`active-memory` openclaw plugin**: AF-108 left this enabled (15s timeout per message). If post-merge testing shows OpenClaw latency regressions, file a follow-up — not in scope for the merge itself.

## Follow-up commit on this branch — Hermes aai-cli support

The merge keeps Hermes aai-cli-free for now. Once the merge is green (tests + smoke test + commit), the **next commit on the same `AF-108-hermes-agents-support` branch** wires aai-cli into Hermes. That commit is its own scope and must not be conflated with the merge.

The follow-up will touch:

1. **`api/domains/agents/aai_cli_artifacts.py`** — parametrize the hard-coded `/home/node` HOME and `/home/node/.config/aai-cli` paths so Hermes can use `/root` + `/opt/data/aai-cli` (or wherever the persistent volume should hold the encrypted secrets). Likely shape: an `AaiCliPaths` dataclass with `OPENCLAW_PATHS` and `HERMES_PATHS` constants; `build_config_toml` and `build_setup_sh` accept it as an argument.
2. **`api/domains/agents/builders/hermes.py:build_hermes_config_map`** — add `aai_cli_config_toml`, `aai_cli_setup_sh`, `skills_json` kwargs that write the three files into the ConfigMap data.
3. **`api/domains/agents/scripts/hermes/start.sh`** — add the `aai-cli-setup.sh` invocation hook and a Python heredoc that reconstructs skill docs under `/workspace/skills/` from the bundled `skills.json` (Hermes has no JS init script; OpenClaw's `init-openclaw.js` equivalent is the model).
4. **`api/domains/agents/service.py`** — drop the `agent_type == OPENCLAW` gates introduced by this merge: in `create_agent` (TOOLS.md pointer + `save_skills`), and in `start_agent` (aai-cli artifact block + `secret.string_data.update(build_env(store))`).
5. **`ui/src/features/agents/components/hire-dialog.tsx`** — drop the `agentType === "openclaw"` filter so the Integrations wizard step shows for Hermes too.
6. **`AAI_CLI_TOOLS_POINTER` path** — verify `./skills/aai-cli/aai-cli_skill.md` resolves under Hermes' `/workspace`. TOOLS.md lands at `/workspace/TOOLS.md` (`scripts/hermes/start.sh` line 39-41), and the new skills block will write under `/workspace/skills/` — so the relative path resolves. Smoke-test this.
7. **`aai-cli` binary on Hermes** — confirm the Hermes image actually contains `aai-cli` before the follow-up lands. OpenClaw bakes it into `agentfarm-openclaw-base`; Hermes currently runs `nousresearch/hermes-agent:latest`. If the binary is absent, either AF-123 (`hermes-base`) bakes it in, or the follow-up's setup.sh falls back to a `command -v aai-cli || exit 0` guard.

## Rollback plan

If the merge goes sideways:

```bash
git merge --abort
make migrate   # re-apply AF-108 migration with old parent
```

The branch returns to its pre-merge state with no DB or working-tree changes.
