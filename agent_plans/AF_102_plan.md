# AF-102 — Microsoft Teams Integration + Slack Credential Refactor

## Context

Agent Farm currently only supports Slack as a communication platform. Slack credentials and settings live directly on the `agent` table. We need to:
1. Refactor Slack credentials/settings into a dedicated `agent_slack_config` table
2. Add a new `agent_teams_config` table for Teams credentials
3. Add a `platform` field to `agent` (enum: slack | teams, **immutable after creation**)
4. Wire up Teams support end-to-end: backend, K8s builders, webhook relay, frontend wizard
5. OpenClaw already supports Teams via the `@openclaw/msteams` plugin (npm package)

Teams uses the Azure Bot Framework webhook model (inbound HTTPS to `/api/messages` on port 3978), unlike Slack's outbound Socket Mode. Since agent pods have no public ingress, the API acts as a centralized webhook relay.

### Key Decisions (from spec Q&A)
- **Platform is immutable** — set at creation, cannot be changed. To switch, user retires and recreates
- **Teams policies deferred** — `agent_teams_config` stores only credentials (App ID, App Password, Tenant ID). Channel/DM access control comes later
- **Conversations parsing** — Teams sessions are in scope. Parser updated to handle `agent:main:msteams:channel:` and `agent:main:msteams:group:` prefixes
- **Webhook relay is a pure pass-through** — no extra auth/protection at API layer. Bot Framework JWT validation happens inside the agent pod
- **Teams agents auto-start** on creation, same as Slack. Health check shows status until Azure endpoint is configured
- **Pairing returns 400 for Teams** — pairing is Slack-only for now
- **Icons** — ship default Agent Farm icons (static PNG assets) in the Teams manifest zip. No dynamic generation for v1
- **Platform badge on agent cards** — not needed for v1. Visible in config drawer
- **Webhook URL** shown in config drawer Endpoint tab (Teams only) + post-creation wizard screen
- **Teams bot builder step** collects App ID early (before credentials step) so manifest can include correct `botId`. Layout: App ID input → bot name/description/color → manifest download → Azure setup instructions
- **Connection test** — rely on existing health check, no extra test button

---

## Phase 1: Database Migration

**New file:** `api/migrations/versions/<rev>_add_platform_and_config_tables.py`

Single migration, in order:

1. Add `platform` column to `agent` (String(10), NOT NULL, server_default `"slack"`, CHECK constraint for `slack`/`teams`)
2. Create `agent_slack_config` table:
   - `id` (UUID PK), `created_at`, `updated_at` — via `BaseModel` from `api/infrastructure/postgres/models.py`
   - `agent_id` (UUID FK → agent.id, UNIQUE, CASCADE)
   - `bot_token_encrypted` (Text, NOT NULL)
   - `app_token_encrypted` (Text, NOT NULL)
   - `channel_ids` (JSON, default `[]`)
   - `dm_user_ids` (JSON, default `[]`)
   - `group_policy` (String, default `"open"`)
   - `dm_policy` (String, default `"open"`)
3. Migrate existing data:
   ```sql
   INSERT INTO agent_slack_config (id, created_at, updated_at, agent_id, bot_token_encrypted, app_token_encrypted, channel_ids, dm_user_ids, group_policy, dm_policy)
   SELECT gen_random_uuid(), now(), now(), id, slack_bot_token_encrypted, slack_app_token_encrypted,
          COALESCE(slack_channel_ids, '[]'::json), COALESCE(slack_dm_user_ids, '[]'::json),
          COALESCE(slack_group_policy, 'open'), COALESCE(slack_dm_policy, 'open')
   FROM agent;
   ```
4. Drop 6 Slack columns from `agent`: `slack_bot_token_encrypted`, `slack_app_token_encrypted`, `slack_channel_ids`, `slack_dm_user_ids`, `slack_group_policy`, `slack_dm_policy`
5. Create `agent_teams_config` table (credentials only — policies deferred):
   - `id` (UUID PK), `created_at`, `updated_at` — via `BaseModel`
   - `agent_id` (UUID FK → agent.id, UNIQUE, CASCADE)
   - `app_id_encrypted` (Text, NOT NULL)
   - `app_password_encrypted` (Text, NOT NULL)
   - `tenant_id` (String(255), NOT NULL)

---

## Phase 2: Backend Models

**File:** `api/domains/agents/models.py`

**New enum:**
```python
class AgentPlatform(str, enum.Enum):
    SLACK = "slack"
    TEAMS = "teams"
```

**Modified `Agent` model:**
- Remove 6 Slack fields
- Add `platform: AgentPlatform` with default `SLACK`, `sa_column=Column(sa.String(10), nullable=False, server_default="slack")`

**New SQLModel `AgentSlackConfig`** (table=True, `__tablename__ = "agent_slack_config"`):
- `agent_id: UUID` (FK agent.id, unique=True, ondelete CASCADE)
- `bot_token_encrypted: str`, `app_token_encrypted: str`
- `channel_ids: list[str]` (JSON), `dm_user_ids: list[str]` (JSON)
- `group_policy: SlackGroupPolicy`, `dm_policy: SlackDmPolicy`

**New SQLModel `AgentTeamsConfig`** (table=True, `__tablename__ = "agent_teams_config"`):
- `agent_id: UUID` (FK agent.id, unique=True, ondelete CASCADE)
- `app_id_encrypted: str`, `app_password_encrypted: str`
- `tenant_id: str` (max_length=255)

**New Pydantic read schemas:**
```python
class AgentSlackConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel_ids: list[str]
    dm_user_ids: list[str]
    group_policy: SlackGroupPolicy
    dm_policy: SlackDmPolicy

class AgentTeamsConfigRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)
    tenant_id: str
```

**Modified `AgentRead`:**
- Add `platform: AgentPlatform`
- Remove flat Slack fields, add `slack_config: AgentSlackConfigRead | None = None` and `teams_config: AgentTeamsConfigRead | None = None`
- Add `webhook_url: str | None = None` (populated for Teams agents)
- Note: `humps` interceptor in `ui/src/shared/api/interceptor/default.ts` auto-converts `snake_case` ↔ `camelCase`, so frontend sees `slackConfig`, `teamsConfig`, `webhookUrl`

**Modified `AgentCreate`:**
- Add `platform: AgentPlatform = AgentPlatform.SLACK`
- Keep existing Slack fields as optional (`str | None = None` for tokens)
- Add `teams_app_id: str | None = None`, `teams_app_password: str | None = None`, `teams_tenant_id: str | None = None`
- Add `@model_validator(mode="after")` that validates:
  - If platform=slack: `slack_bot_token` and `slack_app_token` must be non-None
  - If platform=teams: `teams_app_id`, `teams_app_password`, `teams_tenant_id` must be non-None

**Modified `AgentUpdate`:**
- Add optional Teams fields
- `platform` is NOT in this schema (immutable)

---

## Phase 3: Repository

**File:** `api/domains/agents/repository.py`

New methods:
- `get_slack_config(agent_id: UUID) -> AgentSlackConfig | None`
- `save_slack_config(config: AgentSlackConfig) -> AgentSlackConfig`
- `get_teams_config(agent_id: UUID) -> AgentTeamsConfig | None`
- `save_teams_config(config: AgentTeamsConfig) -> AgentTeamsConfig`
- `get_slack_configs_for_agents(agent_ids: list[UUID]) -> dict[UUID, AgentSlackConfig]` — batch fetch for list views
- `get_teams_configs_for_agents(agent_ids: list[UUID]) -> dict[UUID, AgentTeamsConfig]` — batch fetch for list views

---

## Phase 4: Builders (K8s Resources)

**File:** `api/domains/agents/builders.py`

**Rename** `build_secret()` → `build_secret_slack()` (no behavior change)

**New function `build_secret_teams()`:**
```python
def build_secret_teams(agent_id, org_id, namespace, msteams_app_id, msteams_app_password, msteams_tenant_id, litellm_api_key, litellm_base_url) -> V1Secret:
    string_data = {
        "MSTEAMS_APP_ID": msteams_app_id,
        "MSTEAMS_APP_PASSWORD": msteams_app_password,
        "MSTEAMS_TENANT_ID": msteams_tenant_id,
        "LITELLM_API_KEY": litellm_api_key,
        "LITELLM_BASE_URL": litellm_base_url,
    }
```

**New function `build_openclaw_config_overlay_teams()`:**
```python
def build_openclaw_config_overlay_teams(model, litellm_base_url) -> dict:
    # Same models/agents/tools/memory/plugins sections as Slack
    # Channels section:
    "channels": {
        "msteams": {
            "enabled": True,
            "webhook": {"port": 3978, "path": "/api/messages"},
        }
    },
    "bindings": [{"type": "route", "agentId": "main", "match": {"channel": "msteams"}}]
```
Note: `appId`, `appPassword`, `tenantId` are read by the `@openclaw/msteams` plugin from env vars (`MSTEAMS_APP_ID`, `MSTEAMS_APP_PASSWORD`, `MSTEAMS_TENANT_ID`) injected via K8s Secret — they do NOT go in the config overlay.

**Modify `build_service()`:** Add param `include_webhook_port: bool = False`. When True, append `V1ServicePort(port=3978, target_port=3978, name="webhook")`.

**Update `INIT_OPENCLAW_JS`:** Make allowFrom syncing dynamic — check for both `channels.slack.allowFrom` and `channels.msteams.allowFrom` in the overlay. Add Teams block after existing Slack block:
```javascript
const msteamsAllowFrom = getPath(overlay, ['channels', 'msteams', 'allowFrom']);
if (msteamsAllowFrom !== undefined) {
  const credDir = path.join(HOME, '.openclaw', 'credentials');
  fs.mkdirSync(credDir, { recursive: true });
  fs.writeFileSync(path.join(credDir, 'msteams-allowFrom.json'), JSON.stringify(msteamsAllowFrom, null, 2));
  fs.writeFileSync(
    path.join(credDir, 'msteams-default-allowFrom.json'),
    JSON.stringify({ version: 1, allowFrom: msteamsAllowFrom }, null, 2),
  );
  console.log('[init-openclaw] Synced msteams allowFrom credentials');
}
```

**Update `REPLACE_PATHS`:** Add `['channels', 'msteams', 'allowFrom']`.

---

## Phase 5: Service Layer

**File:** `api/domains/agents/service.py`

**`create_agent()`:**
1. Create `Agent` with `platform=data.platform` (no Slack fields on Agent)
2. If platform=slack: create `AgentSlackConfig` with `encrypt_token(data.slack_bot_token, ...)`, `encrypt_token(data.slack_app_token, ...)`, and policy fields
3. If platform=teams: create `AgentTeamsConfig` with `encrypt_token(data.teams_app_id, ...)`, `encrypt_token(data.teams_app_password, ...)`, `data.teams_tenant_id`
4. Build `AgentRead` with nested config attached

**Helper: `_build_agent_read(agent, slack_config=None, teams_config=None)`:**
Constructs `AgentRead` with nested config and webhook_url (for Teams: `f"{self.config.api_external_url}/api/v1/webhooks/teams/{agent.id}/messages"`)

**`get_agent()`:** Fetch agent, then fetch platform config based on `agent.platform`, pass to `_build_agent_read()`

**`list_agents()`:** Fetch page of agents, batch-fetch all slack configs and teams configs for the page's agent IDs, attach to each `AgentRead`

**`update_agent()`:**
- If agent is Teams and any Slack-specific field is in `updated`: raise 422
- If agent is Slack and any Teams-specific field is in `updated`: raise 422
- Slack field updates: fetch `AgentSlackConfig`, update fields, save
- Teams field updates: fetch `AgentTeamsConfig`, encrypt and update, save

**`start_agent()`:**
```python
if agent.platform == AgentPlatform.SLACK:
    slack_config = self.repository.get_slack_config(agent.id)
    bot_token = decrypt_token(slack_config.bot_token_encrypted, ...)
    app_token = decrypt_token(slack_config.app_token_encrypted, ...)
    overlay = build_openclaw_config_overlay(model, url, slack_config fields...)
    secret = build_secret_slack(..., bot_token, app_token, ...)
    service = build_service(agent.id, org_id, ns)  # no webhook port
elif agent.platform == AgentPlatform.TEAMS:
    teams_config = self.repository.get_teams_config(agent.id)
    app_id = decrypt_token(teams_config.app_id_encrypted, ...)
    app_password = decrypt_token(teams_config.app_password_encrypted, ...)
    overlay = build_openclaw_config_overlay_teams(model, url)
    secret = build_secret_teams(..., app_id, app_password, teams_config.tenant_id, ...)
    service = build_service(agent.id, org_id, ns, include_webhook_port=True)
```

**`pair_agent()`:** Add guard at top: if `agent.platform != AgentPlatform.SLACK`, raise `HTTPException(400, "Pairing is only supported for Slack agents")`. Rest of method reads from `AgentSlackConfig`.

**`list_slack_channels()` / `list_slack_users()`:** Add guard: if `agent.platform != AgentPlatform.SLACK`, raise 400. Decrypt token from `AgentSlackConfig` instead of `Agent`.

**New: `relay_teams_webhook(agent_id, body, headers)`:**
```python
agent = self.repository.get_by_id(agent_id)
if not agent or agent.deleted_at or agent.platform != AgentPlatform.TEAMS:
    raise HTTPException(404)
if agent.status != AgentStatus.RUNNING:
    raise HTTPException(503)
# Proxy using same pattern as fetch_agent_healthz in KubernetesClient
return self.k8s.proxy_to_agent(
    f"agent-{agent.id}", self.config.k8s_namespace, 3978, "/api/messages",
    "POST", body, {"Content-Type": headers.get("content-type", "application/json"),
                    "Authorization": headers.get("authorization", "")}
)
```

**File:** `api/core/config.py`
- Add: `api_external_url: str = ""` (env var: `API_EXTERNAL_URL`)

**File:** `.env` (example addition)
- Add: `API_EXTERNAL_URL=https://api.your-domain.com`

**File:** `api/infrastructure/kubernetes/client.py`
- New method following the same pattern as `fetch_agent_healthz()` (line 258-268):
```python
def proxy_to_agent(self, service_name, namespace, port, path, method, body, headers) -> tuple[int, bytes, dict]:
    host = f"{service_name}.{namespace}"
    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    return resp.status, resp.read(), dict(resp.getheaders())
```

---

## Phase 5b: Conversation Parser for Teams

**File:** `api/domains/conversations/parser.py`

**Teams session key prefixes** (from OpenClaw docs):
- Channel conversations: `agent:main:msteams:channel:<conversationId>`
- Group chats: `agent:main:msteams:group:<conversationId>`

**Inbound message format:** OpenClaw uses the same `custom_message` type with `customType: "openclaw.runtime-context"` for all channels. The content line format differs per channel. For Teams, the format is:
```
[YYYY-MM-DD HH:MM:SS UTC] Teams message in <conversationName> from <userId>: <text>
```
This is analogous to Slack's `Slack message in #channel from USERID: content`.

**Implementation:**
- Add `_INBOUND_TEAMS_RE` regex:
  ```python
  _INBOUND_TEAMS_RE = re.compile(
      r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] "
      r"Teams message in (.+?) from (\S+): (.+)",
      re.DOTALL,
  )
  ```
- Modify `parse_sessions()` to also accept sessions matching `agent:main:msteams:channel:` and `agent:main:msteams:group:` prefixes
- In `_parse_jsonl()`, try `_INBOUND_RE` (Slack) first, then `_INBOUND_TEAMS_RE` if no match. Or accept a `channel_type` parameter to select the correct regex.
- **Note:** If the exact Teams format turns out to differ at runtime, the regex can be adjusted — the structure is discoverable by running a Teams agent and examining the JSONL output. Add a comment noting this.

**File:** `api/domains/conversations/service.py`

- `_channel_sessions()`: Also match `agent:main:msteams:channel:` and `agent:main:msteams:group:` prefixes
- `_distinct_pod_channels()`: Same prefix expansion
- `_slack_maps()` → rename to `_platform_maps()`: Branch on agent platform
  - Slack: existing SlackClient logic (decrypt token from `AgentSlackConfig`)
  - Teams: return empty maps for now (Teams user/channel name resolution deferred — names come from the runtime-context line itself)
- `list_channels()`: Update `_distinct_pod_channels` call and `_slack_maps` → `_platform_maps`

---

## Phase 6: Webhook Relay Route

**New file:** `api/domains/agents/webhook_routes.py`

```python
from fastapi import APIRouter, Request, Response
from uuid import UUID
from typing import Annotated
from fastapi_injector import Injected
from api.domains.agents.service import AgentService

webhook_router = APIRouter(prefix="/webhooks/teams", tags=["webhooks"])

@webhook_router.post("/{agent_id}/messages")
async def teams_webhook(
    agent_id: UUID,
    request: Request,
    service: Annotated[AgentService, Injected(AgentService)],
):
    body = await request.body()
    headers = dict(request.headers)
    status_code, content, resp_headers = service.relay_teams_webhook(agent_id, body, headers)
    return Response(content=content, status_code=status_code,
                    media_type=resp_headers.get("Content-Type", "application/json"))
```

**File:** `api/api_app.py` (line 96, alongside other router registrations)
- Add: `from api.domains.agents.webhook_routes import webhook_router`
- Add: `subapi.include_router(webhook_router)`
- This mounts at `/api/v1/webhooks/teams/{agent_id}/messages`

---

## Phase 7: Frontend — Schemas & Hooks

**File:** `ui/src/features/agents/schemas.ts`

Replace flat Slack fields with nested schemas:
```typescript
export const AgentSlackConfigSchema = z.object({
  channelIds: z.array(z.string()),
  dmUserIds: z.array(z.string()),
  groupPolicy: z.enum(["open", "allowlist"]),
  dmPolicy: z.enum(["off", "open", "allowlist", "pairing"]),
});

export const AgentTeamsConfigSchema = z.object({
  tenantId: z.string(),
});

// Modified AgentSchema:
export const AgentSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  status: z.enum(["STOPPED", "RUNNING", "ERROR"]),
  platform: z.enum(["slack", "teams"]),
  organizationId: z.string().uuid(),
  templateId: z.string().uuid(),
  templateVersion: z.number().int(),
  model: z.string(),
  slackConfig: AgentSlackConfigSchema.nullable().optional(),
  teamsConfig: AgentTeamsConfigSchema.nullable().optional(),
  webhookUrl: z.string().nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});
```
Remove old flat `slackChannelIds`, `slackDmUserIds`, `slackGroupPolicy`, `slackDmPolicy` from `AgentSchema`.

Add types: `AgentSlackConfig`, `AgentTeamsConfig`

**File:** `ui/src/features/agents/hooks/use-create-agent.ts`
```typescript
export type CreateAgentData = {
  name: string;
  platform: "slack" | "teams";
  // Slack (required when platform=slack)
  slackBotToken?: string;
  slackAppToken?: string;
  slackGroupPolicy?: "open" | "allowlist";
  slackDmPolicy?: "off" | "open" | "allowlist" | "pairing";
  // Teams (required when platform=teams)
  teamsAppId?: string;
  teamsAppPassword?: string;
  teamsTenantId?: string;
  // Template
  soulMd: string;
  identityMd: string;
  userMd?: string;
  toolsMd?: string;
  model?: string;
  // ... rest unchanged
};
```
The `humps` interceptor in `ui/src/shared/api/interceptor/default.ts` auto-converts camelCase → snake_case on request and snake_case → camelCase on response. So `teamsAppId` becomes `teams_app_id` in the API request automatically.

**File:** `ui/src/features/agents/hooks/use-update-agent.ts`
- Add optional `teamsAppId`, `teamsAppPassword`, `teamsTenantId` to update data type

---

## Phase 8: Frontend — Wizard

**File:** `ui/src/features/agents/components/hire-dialog-steps.tsx`

**New `WizardStep` type:**
```typescript
type WizardStep = "role" | "platform-choice" | "slack-choice" | "bot-builder"
  | "slack-tokens" | "teams-bot-builder" | "teams-credentials" | "details";
```

**New component: `PlatformChoiceStep`**
- Two `ChoiceCard`s (reuse existing primitive): Slack and Teams
- Props: `platform`, `onChange`

**New component: `TeamsBotBuilderStep`**
Layout (top to bottom):
1. **App ID input** — text field, label "App (client) ID from Azure", hint "Found in your Azure Bot registration under Configuration"
2. **Bot name** — text input (pre-filled from role selection)
3. **Bot description** — text input
4. **Accent color** — color picker (same as Slack bot builder)
5. **Download section** — "Download Teams app package" button that generates zip via JSZip containing:
   - `manifest.json` (generated by `generateTeamsManifest()`)
   - `color.png` (static asset from `ui/public/teams-icon-color.png`)
   - `outline.png` (static asset from `ui/public/teams-icon-outline.png`)
6. **Setup instructions** (numbered `NextStep` components):
   1. Go to Azure Portal → Create a resource → search "Azure Bot"
   2. Create the bot, note the App ID and create a client secret
   3. Under Channels, enable Microsoft Teams
   4. Upload the app package to Teams (Apps → Manage your apps → Upload custom app)

**`generateTeamsManifest()` function:**
```typescript
function generateTeamsManifest(appId: string, botName: string, botDescription: string): string {
  return JSON.stringify({
    "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.13/MicrosoftTeams.schema.json",
    "manifestVersion": "1.13",
    "version": "1.0.0",
    "id": appId,
    "packageName": "com.agentfarm.bot",
    "name": { "short": botName, "full": `${botName} — Agent Farm` },
    "description": { "short": botDescription, "full": `${botDescription}\n\nPowered by Agent Farm.` },
    "icons": { "color": "color.png", "outline": "outline.png" },
    "accentColor": "#4A154B",
    "bots": [{
      "botId": appId,
      "scopes": ["personal", "team", "groupchat"],
      "supportsFiles": false,
      "isNotificationOnly": false,
    }],
    "permissions": ["identity", "messageTeamMembers"],
    "validDomains": [],
  }, null, 2);
}
```

**New component: `TeamsCredentialsStep`**
- **App Password** — `TokenInput` (secret, toggle visibility), hint "Client secret from Azure App Registration"
- **Tenant ID** — text input, hint "Found in Azure Portal → Azure Active Directory → Overview"
- Error display (same pattern as `SlackTokensStep`)
- Note: App ID is NOT collected here — it was already collected in `TeamsBotBuilderStep`

**File:** `ui/src/features/agents/components/hire-dialog.tsx`

**New state variables:**
```typescript
const [platform, setPlatform] = useState<"slack" | "teams">("slack");
const [teamsAppId, setTeamsAppId] = useState("");
const [teamsAppPassword, setTeamsAppPassword] = useState("");
const [teamsTenantId, setTeamsTenantId] = useState("");
const [showTeamsAppPassword, setShowTeamsAppPassword] = useState(false);
```

**Wizard flow (branching on platform):**
```typescript
function getSteps(platform: "slack" | "teams", setupNewBot: boolean): WizardStep[] {
  if (platform === "teams") {
    return ["role", "platform-choice", "teams-bot-builder", "teams-credentials", "details"];
  }
  return setupNewBot
    ? ["role", "platform-choice", "slack-choice", "bot-builder", "slack-tokens", "details"]
    : ["role", "platform-choice", "slack-choice", "slack-tokens", "details"];
}
```

**Navigation (`handleBack`, footer buttons):** Update to use `getSteps()` for determining prev/next step

**`stepTitle()`:** Add cases for `"platform-choice"` → "Choose your platform", `"teams-bot-builder"` → "Build your Teams bot", `"teams-credentials"` → "Connect to Azure"

**`DetailsStep`:** Show `slackGroupPolicy`/`slackDmPolicy` fields only when `platform === "slack"`

**`startHiring()`:**
```typescript
const agent = await createAgent.mutateAsync({
  name, model, platform,
  ...(platform === "slack"
    ? { slackBotToken, slackAppToken, slackGroupPolicy, slackDmPolicy }
    : { teamsAppId, teamsAppPassword, teamsTenantId }),
  soulMd, identityMd, userMd, toolsMd,
});
```

**Post-creation screen:** Branch on platform:
- **Slack** (existing): Show `SlackConfigPanel`
- **Teams** (new): Show:
  1. Success message: "{name} is hired!"
  2. Webhook URL in a copyable code block: `agent.webhookUrl`
  3. Instruction: "Set this URL as the Messaging Endpoint in your Azure Bot registration → Configuration"
  4. "Download Teams app package" button (same zip generation as bot builder step)
  5. "Done" button → `onHired()`

**Provisioning text:** Change `"connecting to Slack"` → `platform === "teams" ? "connecting to Teams" : "connecting to Slack"`

**Dependency:** Add `jszip` npm package — `npm install jszip @types/jszip`

**Static assets:** Create/add two PNG files:
- `ui/public/teams-icon-color.png` — 192×192, Agent Farm logo on solid background
- `ui/public/teams-icon-outline.png` — 32×32, white-only outline version

---

## Phase 9: Frontend — Config Drawer

**File:** `ui/src/features/agents/components/config-drawer.tsx`

**Platform-aware tabs:**
```typescript
const tabs: [string, string, boolean][] = [
  ["personality", "Personality", true],
  ["secrets", "Keys", true],
  ...(agent.platform === "slack" ? [["channels", "Channels", true] as const] : []),
  ...(agent.platform === "teams" ? [["endpoint", "Endpoint", true] as const] : []),
  ["skills", "Skills", false],
  ["k8s", "Infrastructure", false],
  ["danger", "Danger zone", true],
];
```

**"Keys" tab — platform branching:**
- If `agent.platform === "slack"`: existing Slack token inputs (xapp- and xoxb-)
- If `agent.platform === "teams"`: three fields:
  - App ID (text, write-only, placeholder "Leave blank to keep existing")
  - App Password (`TokenInput`, write-only)
  - Tenant ID (text, write-only)
  - Save button calls `updateAgent.mutateAsync({ agentId, teamsAppId, teamsAppPassword, teamsTenantId })`

**New "Endpoint" tab (Teams only):**
```tsx
{tab === "endpoint" && (
  <div>
    <Hint>This is the messaging endpoint URL. Configure it in your Azure Bot registration.</Hint>
    <div className="flex items-center gap-2 p-4 rounded-xl font-mono text-sm"
         style={{ background: "var(--bg-soft)", border: "1px solid var(--line)" }}>
      <span className="flex-1 break-all" style={{ color: "var(--ink-2)" }}>{agent.webhookUrl}</span>
      <button className="af-btn af-btn-sm" onClick={() => navigator.clipboard.writeText(agent.webhookUrl!)}>
        Copy
      </button>
    </div>
  </div>
)}
```

**"Infrastructure" tab:** For Teams agents, show port 3978 in the Service display: `"ClusterIP · :8080, :3978"`

**File:** `ui/src/features/agents/components/slack-config-panel.tsx`

Update all property access to use nested config:
- `agent.slackChannelIds` → `agent.slackConfig?.channelIds ?? []`
- `agent.slackDmUserIds` → `agent.slackConfig?.dmUserIds ?? []`
- `agent.slackGroupPolicy` → `agent.slackConfig?.groupPolicy ?? "open"`
- `agent.slackDmPolicy` → `agent.slackConfig?.dmPolicy ?? "off"`

---

## Phase 10: Tests

**File:** `api/tests/steps/agent.py`

Add constants:
```python
TEST_TEAMS_APP_ID = "test-teams-app-id"
TEST_TEAMS_APP_PASSWORD = "test-teams-app-password"
TEST_TEAMS_TENANT_ID = "test-tenant-id"
```

Modify `there_is_an_agent()`:
- Accept `platform: AgentPlatform = AgentPlatform.SLACK` parameter
- Create `Agent` without Slack fields, with `platform=platform`
- If platform=SLACK: create `AgentSlackConfig` with test tokens
- If platform=TEAMS: create `AgentTeamsConfig` with test credentials

**File:** `api/tests/steps/database.py`

Add to table truncation: `agent_slack_config`, `agent_teams_config`

**File:** `api/tests/integration/test_agents.py`

Update existing tests:
- `_VALID_CREATE` dict: add `"platform": "slack"`, keep Slack token fields
- Response assertions: `body["slack_config"]["channel_ids"]` instead of `body["slack_channel_ids"]`
- Agent list assertions: same nested structure

New tests:
1. `test_create_teams_agent_returns_201` — POST with platform=teams + Teams credentials, verify response has `platform: "teams"`, `teams_config.tenant_id`, `webhook_url`
2. `test_create_teams_agent_missing_credentials_returns_422` — Omit `teams_app_password`, verify 422
3. `test_create_slack_agent_missing_tokens_returns_422` — Omit `slack_bot_token`, verify 422
4. `test_start_teams_agent_creates_correct_k8s_resources` — Mock K8s, verify `create_secret` called with `MSTEAMS_APP_ID` etc., `create_service` called with port 3978
5. `test_teams_webhook_relay_proxies_to_pod` — Mock `proxy_to_agent`, POST to webhook endpoint, verify forwarded
6. `test_teams_webhook_relay_returns_404_for_slack_agent` — POST webhook for Slack agent → 404
7. `test_teams_webhook_relay_returns_503_for_stopped_agent` — POST webhook for stopped Teams agent → 503
8. `test_update_teams_agent_rejects_slack_fields` — PATCH with `slack_bot_token` on Teams agent → 422
9. `test_pair_teams_agent_returns_400` — POST pair on Teams agent → 400

**File:** `api/tests/unit/test_conversation_parser.py`

New test fixtures for Teams:
- Sample sessions.json with `agent:main:msteams:channel:conv123` key
- Teams inbound JSONL line (custom_message, content: `[2026-05-24 10:00:00 UTC] Teams message in General from user@tenant: hello`)
- Outbound JSONL line (same format as Slack — platform-agnostic)

New tests:
- `test_parses_teams_inbound_message` — verify Teams regex extracts sender, channel, content
- `test_parses_teams_outbound_message` — verify delivery-mirror message extracted
- `test_skips_non_msteams_non_slack_sessions` — other prefixes ignored
- `test_handles_both_slack_and_teams_sessions` — mixed sessions.json

**File:** `api/tests/integration/test_slack_config.py` (e2e tests)
- Update agent creation payload and assertions for nested `slack_config` schema

---

## Phase 11: Container Image

**File:** `openclaw-base/Dockerfile`

Add `@openclaw/msteams` to the npm install line (find the existing `npm install -g openclaw` line and append):
```dockerfile
RUN npm install -g openclaw @openclaw/msteams
```

---

## Implementation Order

1. Container image (install `@openclaw/msteams`) — independent
2. Database migration
3. Backend models + repository
4. Builders (new Teams functions + modify existing)
5. Service layer (refactor all methods for platform awareness)
6. Conversation parser (Teams session support)
7. Webhook relay route + registration in `api_app.py`
8. Tests (update steps, update existing tests, add Teams tests)
9. Frontend schemas + hooks
10. Frontend wizard (new steps + flow branching + static icon assets + jszip)
11. Frontend config drawer

---

## Verification

1. **Migration**: Run `alembic upgrade head`, verify `agent_slack_config` has all migrated data, `agent` table has `platform` column but no Slack columns
2. **API — Slack agents**: Create, start, stop, update Slack agent — all existing behavior unchanged
3. **API — Teams agents**: Create Teams agent → response has `platform: "teams"`, `teams_config.tenant_id`, `webhook_url`
4. **API — Teams start**: Start Teams agent → K8s mock gets Secret with `MSTEAMS_*` env vars, overlay with `channels.msteams`, Service with port 3978
5. **API — Validation**: Create Teams agent without `teams_app_password` → 422. Update Teams agent with `slack_bot_token` → 422. Pair Teams agent → 400
6. **Webhook relay**: POST to `/api/v1/webhooks/teams/{id}/messages` → proxied to pod. POST for Slack agent → 404. POST for stopped agent → 503
7. **Conversations**: Teams sessions parsed, messages appear in channel list and messages endpoints
8. **Frontend — Slack wizard**: Complete end-to-end, no regressions
9. **Frontend — Teams wizard**: Platform choice → bot builder (enter App ID, download manifest zip) → credentials → details → provisioning → post-creation (webhook URL + download)
10. **Frontend — Config drawer**: Slack agent shows Channels tab. Teams agent shows Endpoint tab with webhook URL. Keys tab shows platform-appropriate fields
11. **Run tests**: `pytest api/tests/ -v` — all pass