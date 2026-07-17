# AF-152: Integrate Firecrawl

## Context

Agent-farm's predecessor (OCBW) had Firecrawl integration for both OpenClaw (plugin-based) and Hermes (config + env vars) runtimes. AF-108 deliberately skipped porting it ("out of scope for v1"). This task adds it back: a self-hosted Firecrawl instance deployed alongside the existing services, wired into both agent runtimes so deployed agents can fetch web content, with an optional per-agent API key override.

**Acceptance criteria:**
1. Self-hosted Firecrawl deployed alongside other services
2. OCBW's approach is mirrored where applicable
3. Deployed agents can use Firecrawl to fetch web content
4. Users can provide their own Firecrawl API key per agent

---

## Implementation Plan

### Step 1: API Models — Add `SecretProvider.FIRECRAWL` ✅

DB migration added — `ck_agent_secret_provider` check constraint needed updating.

**File: `api/domains/agents/models.py`**
- Add `FIRECRAWL = "firecrawl"` to `SecretProvider` enum (after ZOHO_CALENDAR)
- Add `FirecrawlContent(SecretContent)` model with fields: `api_key: str`, `base_url: str = ""`
- Add entry to `PROVIDER_DISPLAY_NAMES`: `SecretProvider.FIRECRAWL: "Firecrawl credential"`
- Add entry to `PROVIDER_CONTENT_MODELS`: `SecretProvider.FIRECRAWL: FirecrawlContent`

**Tests first:** Unit test that `FirecrawlContent` validates correctly, `validate_content` works for FIRECRAWL provider, and rejects invalid payloads (extra fields, missing api_key).

---

### Step 2: API Config — Add Firecrawl settings ✅

**File: `api/core/config.py`**
- Add `agent_firecrawl_base_url: str = ""` (populated from `AGENT_FIRECRAWL_BASE_URL` env var)
- Add `agent_firecrawl_api_key: str = ""` (platform-level key, populated from `AGENT_FIRECRAWL_API_KEY`)

---

### Step 3: Hermes Builder — Add Firecrawl config

Mirrors OCBW's `build_hermes_config()` with `firecrawl_enabled` and `build_hermes_env()`.

**File: `api/domains/agents/builders/hermes.py`**

`build_hermes_config()` — add parameters:
- `firecrawl_base_url: str = ""`
- `firecrawl_api_key: str = ""`

When both are non-empty, add to the config dict (mirroring OCBW exactly):
```python
config["web"] = {"backend": "firecrawl"}
config["browser"] = {"cloud_provider": "firecrawl"}
```

`build_secret_hermes_slack()` — add optional parameters:
- `firecrawl_api_key: str = ""`
- `firecrawl_base_url: str = ""`

When non-empty, add to `string_data`:
```python
"FIRECRAWL_API_KEY": firecrawl_api_key,
"FIRECRAWL_API_URL": firecrawl_base_url,
"FIRECRAWL_BROWSER_TTL": "600",
```

**Tests first:** Unit tests for `build_hermes_config()` with/without firecrawl params, verifying the `web` and `browser` keys appear/absent. Tests for `build_secret_hermes_slack()` verifying `FIRECRAWL_*` env vars in string_data.

---

### Step 4: OpenClaw Builder — Add Firecrawl plugin config

Mirrors OCBW's plugin overlay pattern.

**File: `api/domains/agents/builders/openclaw.py`**

`build_openclaw_config_overlay()` — add parameters:
- `firecrawl_base_url: str = ""`
- `firecrawl_api_key: str = ""`

When both are non-empty, add firecrawl to the plugin allowlist and entries:
```python
# Add "firecrawl" to plugins.allow list
# Add plugin entries:
"plugins": {
    "entries": {
        "firecrawl": {
            "enabled": True,
            "config": {
                "webSearch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                },
                "webFetch": {
                    "apiKey": "${FIRECRAWL_API_KEY}",
                    "baseUrl": firecrawl_base_url,
                    "onlyMainContent": True,
                    "maxAgeMs": 172800000,
                    "timeoutSeconds": 60,
                },
            },
        },
    },
}
# Set tools.web.fetch.provider = "firecrawl"
# Set tools.web.search.enabled = True, tools.web.search.provider = "firecrawl"
```

`build_secret_slack()` and `build_secret_teams()` — add optional `firecrawl_api_key` param. When non-empty, add `"FIRECRAWL_API_KEY": firecrawl_api_key` to `string_data`.

Same pattern for `build_openclaw_config_overlay_teams()`.

**Tests first:** Unit tests for the overlay dict structure with/without firecrawl, verifying plugin entries and tools config. Tests for secrets containing `FIRECRAWL_API_KEY`.

---

### Step 5: Agent Service — Wire Firecrawl into `start_agent()` ✅

**File: `api/domains/agents/service.py`**

In `start_agent()`, after decrypting agent secrets (line ~1017):
1. Check if agent has a `SecretProvider.FIRECRAWL` secret → use that `api_key`
2. Otherwise fall back to `self.config.agent_firecrawl_api_key` (platform-level)
3. For `base_url`: if per-agent secret has a non-empty `base_url`, use it; otherwise fall back to `self.config.agent_firecrawl_base_url`
4. Mutate already-built config/overlay/secret objects with resolved key + URL

**Key + URL override logic:**
- Per-agent secret can override **both** the API key and the base URL
- This lets users point to Firecrawl Cloud (`https://api.firecrawl.dev`) with their own key
- If only `api_key` is set in the per-agent secret (no `base_url`), the agent still uses the platform's self-hosted URL — but this will fail auth since the self-hosted server only knows the platform `TEST_API_KEY`
- If neither platform nor per-agent key is set → firecrawl not configured (graceful skip)

**Tests first:** Integration tests verifying:
- Agent with per-agent FIRECRAWL secret (key only) → agent pod gets that key + platform URL
- Agent with per-agent FIRECRAWL secret (key + base_url) → agent pod gets both overrides
- Agent without FIRECRAWL secret → agent pod gets platform-level key + URL
- Neither set → firecrawl not configured (no FIRECRAWL_* env vars)

---

### Step 6: Helm — agentfarm-api chart updates

**File: `helm/agentfarm-api/values.yaml`**
```yaml
agentFirecrawlBaseUrl: "http://firecrawl:3002"
agentFirecrawlApiKey: ""
```

**File: `helm/agentfarm-api/templates/deployment.yaml`** — add env vars:
```yaml
- name: AGENT_FIRECRAWL_BASE_URL
  value: "{{ .Values.agentFirecrawlBaseUrl }}"
```

**File: `helm/agentfarm-api/templates/secret.yaml`** — add:
```yaml
AGENT_FIRECRAWL_API_KEY: {{ .Values.agentFirecrawlApiKey | default "" | quote }}
```

---

### Step 7: Helm — New `helm/firecrawl/` chart

Self-hosted Firecrawl deployment. Services (based on [official docker-compose](https://github.com/firecrawl/firecrawl/blob/main/docker-compose.yaml)):

| Service | Image | Port | Purpose |
|---|---|---|---|
| firecrawl | `ghcr.io/firecrawl/firecrawl` | 3002 | API + workers |
| playwright | `ghcr.io/firecrawl/playwright-service:latest` | 3000 | Browser automation |
| redis | `redis:alpine` | 6379 | Rate limiting, caching |
| rabbitmq | `rabbitmq:3-management` | 5672 | Job queue |

Postgres for Firecrawl reuses the existing `helm/postgres` chart as a new helmfile release (`postgres-firecrawl`), following the `postgres-litellm` precedent.

Chart structure:
```
helm/firecrawl/
  Chart.yaml
  values.yaml
  templates/
    _helpers.tpl
    deployment-api.yaml        # Firecrawl API
    deployment-playwright.yaml # Playwright service
    deployment-redis.yaml      # Redis
    deployment-rabbitmq.yaml   # RabbitMQ
    service-api.yaml           # ClusterIP port 3002
    service-playwright.yaml    # ClusterIP port 3000
    service-redis.yaml         # ClusterIP port 6379
    service-rabbitmq.yaml      # ClusterIP port 5672
    secret.yaml                # FIRECRAWL_API_KEY, BULL_AUTH_KEY
```

---

### Step 8: Helmfile — Add Firecrawl releases

**File: `helmfile.yaml.gotmpl`**

Add two releases:
```yaml
- name: postgres-firecrawl
  chart: ./helm/postgres
  # Reuses existing postgres chart
  set:
    - name: db.user / db.password / db.name
      # from POSTGRES_FIRECRAWL_* env vars

- name: firecrawl
  chart: ./helm/firecrawl
  needs:
    - agent-farm/postgres-firecrawl
  set:
    - name: firecrawlApiKey
      # from FIRECRAWL_API_KEY env var
    - name: databaseUrl
      # postgres connection string
```

Also add `agentFirecrawlApiKey` set to the `agentfarm-api` release.

---

### Step 9: Deploy env spec

**File: `.env.deploy.spec`** — add:
```env
# ── Firecrawl ────────────────────────────────────────────────────────────────
FIRECRAWL_API_KEY=
POSTGRES_FIRECRAWL_USER=firecrawl
POSTGRES_FIRECRAWL_PASSWORD=
POSTGRES_FIRECRAWL_DB=firecrawl
```

---

### Step 10: UI — Add Firecrawl integration provider

**File: `ui/src/features/agents/integrations.ts`**

Add to `INTEGRATION_PROVIDERS` array:
```ts
{
  id: "firecrawl",
  label: "Firecrawl",
  scopeNote: "Optional — agents use the platform Firecrawl by default. Provide your own API key and URL to use Firecrawl Cloud or another instance.",
  fields: [
    { key: "apiKey", label: "API key", type: "secret", required: true, placeholder: "fc-…" },
    { key: "baseUrl", label: "Base URL", type: "text", required: false, placeholder: "https://api.firecrawl.dev", hint: "Leave empty to use the platform's self-hosted Firecrawl." },
  ],
},
```

---

### Step 10a: Backfill — Add `base_url` to `FirecrawlContent` and service wiring

Since Steps 1 and 5 were implemented before the key+URL override decision, this step backfills the changes:

**File: `api/domains/agents/models.py`**
- Add `base_url: str = ""` to `FirecrawlContent` (optional field, empty default)

**File: `api/domains/agents/service.py`** (line ~1017–1053)
- After resolving `fc_api_key`, also resolve `fc_base_url`:
  ```python
  fc_base_url = (
      fc_content.base_url
      if isinstance(fc_content, FirecrawlContent) and fc_content.base_url
      else self.config.agent_firecrawl_base_url
  )
  ```

**File: `api/tests/unit/test_agent_secrets.py`**
- Update existing `FirecrawlContent` tests to cover `base_url` field (present, absent, empty)

**File: `api/tests/integration/test_agents.py`**
- Add test for per-agent key + base_url override

---

## Design Decisions

- **Always on**: All agents get Firecrawl automatically via the platform-level API key (mirrors OCBW's `capabilities.defaults: ["firecrawl"]`). Users can optionally override with their own key per agent via the integrations UI.
- **Key + URL override**: Per-agent Firecrawl secret includes an optional `base_url` alongside `api_key`. When set, the agent uses the user's Firecrawl instance (e.g. Firecrawl Cloud at `https://api.firecrawl.dev`). When empty, the agent uses the platform self-hosted instance. Key-only override still works if additional keys are registered in the self-hosted Firecrawl DB.
- **Reuse postgres chart**: Firecrawl's Postgres runs as a separate `postgres-firecrawl` helmfile release reusing `helm/postgres`, matching the `postgres-litellm` precedent.
- **Full implementation**: All 10 steps in one pass — backend, Helm, and UI.

## Execution Order (TDD)

Each step is independently testable and committable. We implement one step at a time:

1. **Models** (Step 1) — smallest change, pure data
2. **Config** (Step 2) — two new fields
3. **Hermes builder** (Step 3) — tests first, then implementation
4. **OpenClaw builder** (Step 4) — tests first, then implementation
5. **Service wiring** (Step 5) — tests first, then implementation
6. **agentfarm-api Helm** (Step 6) — deployment config
7. **Firecrawl Helm chart** (Step 7) — new chart
8. **Helmfile** (Step 8) — wire everything together
9. **Deploy spec** (Step 9) — env template
10. **UI** (Step 10) — integration provider entry

## Verification

- `make check-api` and `make test-api` pass after Steps 1–5
- `make lint-ui` and `pnpm -s tsc --noEmit` pass after Step 10
- Helm template renders: `helm template ./helm/firecrawl` produces valid YAML
- Agent start with firecrawl configured → agent pod has `FIRECRAWL_API_KEY` and `FIRECRAWL_API_URL` env vars
- Agent start without firecrawl → no firecrawl env vars, no errors

## Key Patterns Reused

- `SecretProvider` / `SecretContent` pattern (from GitHub, Jira, etc.)
- `PROVIDER_DISPLAY_NAMES` / `PROVIDER_CONTENT_MODELS` registries
- `build_hermes_config()` / `build_secret_hermes_slack()` function signature extension
- `build_openclaw_config_overlay()` / `build_secret_slack()` function signature extension
- `helm/litellm/` chart structure for the new `helm/firecrawl/` chart
- `helm/postgres` chart reuse for `postgres-firecrawl` release
- `INTEGRATION_PROVIDERS` array in `integrations.ts` for UI
