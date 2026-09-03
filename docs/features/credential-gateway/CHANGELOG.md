# Credential Gateway — change log

Status: Active
Epic: credential gateway (ticket pending)
Related context: [`../../adr/2026-09-02-credential-gateway-egress-modes.md`](../../adr/2026-09-02-credential-gateway-egress-modes.md), [`../../adr/2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md`](../../adr/2026-09-02-integration-plugin-and-runtime-tool-adapter-seams.md), [`../integrations.md`](../integrations.md)

## Current state

- **Delivered:** the Integration Plugin seam; the credential gateway as a separate deployment; token issue/revoke/resolve; and the `GATEWAY_PROXY` forward path, with GitHub as the first provider that supports it.
- **In transition:** `CREDENTIAL_GATEWAY_PROVIDERS` is empty by default, so every provider is effectively `DIRECT` and nothing changes until an operator opts GitHub in. `PROVIDER_DISPLAY_NAMES`, `PROVIDER_CONTENT_MODELS`, and `PROVIDER_VALIDATORS` still live outside the plugins (import cycle) and are pinned by contract test rather than derived.
- **Next:** NetworkPolicy default-deny egress (Slice 4), then the remaining aai-cli providers (Slice 5) and the Google token broker (Slice 6).
- **Blockers:** none. Slice 4 must not land until GitHub is actually enabled in at least one environment, or agents lose access to everything not yet migrated. `aai-cli` must ship `auth_type = "gateway"` before GitHub can be enabled anywhere real — the API emits that profile shape today, but the CLI is a separate repo.

## Changes

### 2026-09-02 — Slice 3 — GATEWAY_PROXY forward path for GitHub

- **Delivered:** `ANY /gateway/v1/p/{provider}/{path}` resolves the Gateway Token, decrypts the Agent Secret (following a Shared Credential when set), strips the agent's `Authorization` and hop-by-hop headers, applies the real provider credential through `apply_upstream_auth`, forwards, and returns the upstream status and body unchanged. `GithubPlugin` gained `upstream_base_url` and `apply_upstream_auth`.
- **Rollout model:** `egress_mode` on a plugin is a *capability*; `Config.credential_gateway_providers` is the *switch*. `effective_egress_mode` is the single place the two combine, so Gateway Token issuance and the aai-cli artifact builders cannot disagree about where a credential goes. Enabling and rolling back are config changes, not deploys.
- **What actually removes the credential:** `store_providers_for` excludes gateway-routed providers from the aai-cli secret store, so the real token is in neither the pod Secret nor `aai-secrets.enc.json`. The profile block alone would not have done it.
- **Refusals:** wrong-provider path, rolled-back provider, missing credential, unknown and revoked tokens all return the same opaque 403 as `/identity`, so an agent cannot probe which applies. An unreachable upstream is a 502 and is distinguished from an upstream error status, which passes through untouched.
- **Redirects:** followed gateway-side, because NetworkPolicy will deny the pod any egress except the gateway. Authorization is re-applied only while the redirect stays on the origin host — carrying a provider credential to a redirect target would hand it to whoever controls that host. Bounded at 5 hops.
- **Follow-up:** `aai-cli` needs to implement `auth_type = "gateway"` in its own repo before GitHub can be enabled outside tests.

### 2026-09-02 — Slack retired as a tool Integration

Not a gateway slice; recorded here because it landed mid-epic and changed the plugin catalogue from ten providers to nine.

- **Why:** the shipped Slack Platform Plugin replaces the Slack tool Integration outright, and it owns that credential. Keeping a second Slack credential class meant two places to configure, validate, and revoke the same access.
- **Delivered:** `SecretProvider.SLACK`, `SlackContent`, `SlackPlugin`, `validate_slack`, and the UI credential form are removed. A Slack credential is now only ever a Communication Connection credential and never an Agent Secret.
- **Migration `59bd5956b22a`:** deletes `agent_secret` and `shared_credential` rows with `provider = 'slack'`. This destroys credential material deliberately — no runtime could use those tokens any more, and leaving them would raise `ValueError` when agent start coerces the stored string back to the enum.
- **Tests:** 15 Slack-specific tests removed. Four general tests that merely used Slack as their example (`test_env_var_for`, `test_config_toml_emits_only_present_store_profiles`, `test_tool_context_md_lists_providers_without_metadata`, `test_integrations_policy_md_never_leaks_tokens`) were kept and re-pointed at Pipedrive.

### 2026-09-02 — Slice 2 — Credential gateway, identity only

- **Decided:** the gateway is a **separate Deployment** (own Service, port 8003, independent replicas and resources), because it lands on the request path of every agent tool call and its availability and scaling should not be coupled to the product API's. It ships in the **same image**, so the Integration Plugins it imports need no separate packaging — the concern that made this decision blocking does not arise.
- **Delivered:** `gateway_token` table; `CredentialGatewayService` issue/revoke/resolve; `GET /gateway/v1/identity` returning `(agent_id, organization_id, provider)` and one structured 403 for every rejection; `gateway_app.py` + `gateway_main.py`; Helm `gateway-deployment.yaml` and values block; chart `0.7.9` → `0.8.0`.
- **Changed:** agent start issues and rotates Gateway Tokens for gateway-served providers and writes `AF_GATEWAY_TOKEN_<PROVIDER>` plus `AF_GATEWAY_URL` into the pod Secret; agent stop revokes them. Issuance is gated on `EgressMode`, so today it is a no-op and the pod Secret is unchanged.
- **Security shape:** tokens are stored as SHA-256 hashes, not encrypted — the gateway resolves by the token alone, and Fernet ciphertext is non-deterministic and so not indexable. Nothing needs the plaintext back. A slow password hash would be wrong for 32 bytes of CSPRNG entropy on a per-tool-call path. One token per `(Agent, provider)`, so revoking one Integration cannot take the others down. Revocation is a stamp, not a delete, so the audit trail outlives the credential.
- **Deferred:** resolution audit currently emits a structured log line and a Prometheus counter through `GatewayAuditSink`. The durable buffering/disk-spool implementation that survives a 60s ingest outage is Slice 8 and replaces the sink without touching call sites.
- **Follow-up:** Slice 3 flips GitHub to `GATEWAY_PROXY`, which is what first makes issuance non-empty.

### 2026-09-02 — Slice 1 — Integration Plugin and Runtime Tool Adapter seams

- **Delivered:** `IntegrationPlugin` (generic over its credential model), the `AaiCliIntegration`/`AaiCliPlugin` aai-cli surface, `EgressMode`, and `IntegrationPluginRegistry` with import-time coherence validation. All ten providers ported as `EgressMode.DIRECT`.
- **Changed:** `aai_cli_artifacts.py` keeps its public surface but derives `PROFILE_SLUGS` and `provider_secrets_map` from the registry and delegates every per-provider branch to a plugin; the `_PROFILE_BUILDERS` dict, the eight `_x_block` builders, `_INTEGRATION_LABELS`, `_INTEGRATION_CAPABILITIES`, `_repo_scoped_profile_line`, and the two `isinstance` chains are gone. `SHARED_CREDENTIAL_ALLOWED_PROVIDERS` and `aai_cli_skills._REQUIRED_PROVIDERS` are now derived from the plugins. `service.py` is untouched.
- **Verified:** every artifact (config.toml, setup.sh, env, tools_md, agents_md, gog env/policy/setup) is byte-identical across a full and a variant provider map, both runtime home dirs, and the empty case. 915 unit and 825 integration tests pass with no existing test modified.
- **Follow-up:** Slice 2 (gateway identity) is unblocked once the deployment shape is decided.

### 2026-09-02 — Slice 0 — `GOG_READONLY` backstop

- **Delivered:** a read-only Google Workspace credential now sets `GOG_READONLY=1`, so gog rejects mutating API requests locally before dispatch instead of relying solely on Google refusing the write.
- **Changed:** `build_gog_env` emits the variable only when `content.read_only`; `build_gog_policy_md` now tells the agent writes are rejected by `gog`, not by Google. `docs/features/integrations.md` records the backstop and its limit.
- **Follow-up:** an environment variable is unsettable by an agent with a shell. The compiled safety-profile binary in Slice 7 is the version that cannot be bypassed.
