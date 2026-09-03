# Integrations extend through two seams: Integration Plugin and Runtime Tool Adapter

Status: Proposed
Date: 2026-09-02
Origin: follows the shipped Platform Plugin boundary in Communications

Adding a tool Integration becomes one plugin file plus a skill, mirroring the Platform Plugin boundary in Communications. Unlike platforms, integrations vary along two independent axes — the credential/provider and the agent-side CLI that reaches it — so they get two seams rather than one: `IntegrationPlugin` per provider and `RuntimeToolAdapter` per CLI.

## Context

Adding a provider today means editing twelve sites across four layers: `SecretProvider`, `PROVIDER_DISPLAY_NAMES` and the content-model union in `agents/models.py`; `provider_secrets_map`, `PROFILE_SLUGS`, a `_x_block()` builder, `_PROFILE_BUILDERS`, and an `isinstance` chain in `build_tool_context_md` in `aai_cli_artifacts.py`; `PROVIDER_VALIDATORS`; the skill seeder and a bundled `SKILL.md`; and a UI Zod schema and form.

Google Workspace bypasses the entire aai-cli block and carries its own `gog_artifacts.py` and OAuth routes. That is not a special case — it is a missing abstraction. The moment a third CLI (`some_service_cli`) arrives, the same bypass is duplicated again.

Communications solved the analogous problem with `PlatformPlugin` plus a code-owned `PlatformPluginRegistry`: typed settings and credential schemas, external validation, credential fingerprinting, and provider behavior on one object, with the generic persistence, routes, and schema-driven UI carrying no per-platform branches.

That model does not transfer directly. A platform is one thing; an integration is two. Provider and runtime tool are many-to-one: adding Notion-over-aai-cli touches only the provider, and adding `some_service_cli` touches only the tool. A single fused interface would force re-implementing provider concerns for every provider a new CLI serves.

## Decision

Add both seams under `api/domains/integrations/plugins/`.

**`IntegrationPlugin`** — one per provider. Carries `key` (replacing the `SecretProvider` member), `display_name`, `schema_version`, `credentials_model`, `egress_mode`, `runtime_tool`, `shared_credential_eligible`, and `bundled_skill_keys`. Declares `validate_external` for live credential checks; `upstream_base_url` and `apply_upstream_auth` for `GATEWAY_PROXY` providers; `mint_upstream_token` for `TOKEN_BROKER` providers; and an optional `tool_context_md`.

`apply_upstream_auth` is a method rather than a declarative scheme table covering bearer, basic, custom header, and query parameter. Writing Jira's `Basic base64(email:token)` and a future request-signing provider costs the same amount of interface, and no configuration language has to be extended to reach the second one.

**`RuntimeToolAdapter`** — one per CLI. `materialize(bindings, home_dir, gateway_base_url) -> RuntimeArtifacts`, where `RuntimeArtifacts` is files, environment, and an `agents_md` policy block, and carries no Kubernetes types — preserving the existing "pure string/dict builders" convention. Three implementations: `AaiCliAdapter`, `GogAdapter`, and `NoToolAdapter` for env-only providers such as Firecrawl.

**Registry validation at import time**, extending `PlatformPluginRegistry`'s constructor checks with the coherence rules the two axes create: `GATEWAY_PROXY` requires `upstream_base_url` and `apply_upstream_auth`; `TOKEN_BROKER` requires `mint_upstream_token`; every `runtime_tool` resolves to a registered adapter; every `bundled_skill_keys` entry exists in the seeder. A malformed plugin fails startup rather than an agent start, and one parametrized test over the registry covers every provider's contract.

Plugins are trusted release artifacts, not dynamically installed packages — the same stance as Platform Plugins, and a stronger requirement here because these code paths decrypt credentials and mint upstream tokens. No entry-point discovery, no runtime registration.

## Boundary constraint

`apply_upstream_auth` is called by the gateway at request time; `materialize` is called by the API at agent start. If the gateway deploys separately, these run in different processes. Plugin modules therefore depend only on credential models, stdlib, and the HTTP client — never on routes, the SQLAlchemy session, or the Kubernetes client. Violating this is what would force the gateway back into the API deployment.

## Consequences

- A new provider on an existing CLI is one plugin file plus one `SKILL.md`. No enum edit, no builder-dict entry, no validator-dict entry, no `isinstance` branch, and no UI schema — the form renders from `credentials_model.model_json_schema()`, as the Communications UI already does.
- A new provider requires no gateway deploy, because egress behavior travels on the plugin.
- A new CLI is one adapter plus its providers' plugins; it does not touch existing providers.
- `SecretProvider` stops being the source of truth and becomes a stored column value validated against registry keys. Existing rows are unaffected because plugin keys reuse the current enum values.
- `EgressMode.DIRECT` reproduces current behavior exactly, so porting all ten providers is a pure refactor that lands before any gateway work and is worth doing on its own merits.
- Two seams are more surface than one. The cost is justified only because provider and tool genuinely vary independently; if a future CLI is ever 1:1 with a single provider, it still pays for two files.
