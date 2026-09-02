# aai-cli PostHog Skill

Agent reference for the `aai-cli posthog` command group.

## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile & Authentication

PostHog profiles use personal API tokens (`Authorization: Bearer <token>`):

```toml
[profiles.posthog-work]
provider = "posthog"
token = "phx_your_personal_api_key"
project_id = "1"
base_url = "https://us.i.posthog.com"
```

Environment variable fallbacks:
- `POSTHOG_API_KEY` or `POSTHOG_PERSONAL_API_KEY`
- `POSTHOG_PROJECT_ID`
- `POSTHOG_HOST` or `POSTHOG_BASE_URL` (defaults to `https://us.i.posthog.com`)

## Response shapes

Successful command output is JSON on stdout, wrapped with an `_aai` pagination-metadata block:

```json
{
  "_aai": {
    "pagination": {
      "continuation": null,
      "has_more": false,
      "instruction": "...",
      "next_command": null,
      "returned_count": 2,
      "status": "complete"
    }
  },
  "count": 2,
  "next": null,
  "previous": null,
  "results": [...]
}
```

## Command Surface & Usage

### 1. Projects (`posthog projects`)

#### `projects list`
List accessible PostHog projects in the workspace.

```bash
aai-cli posthog projects list [--limit N] [--offset N]
```

Example response:
```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Default Project",
      "api_token": "phc_...",
      "timezone": "UTC",
      "uuid": "01950e93-a442-0000-84c4-aa3dfac9cdbf"
    }
  ]
}
```

#### `projects get`
Fetch details for a specific PostHog project by ID.

```bash
aai-cli posthog projects get --project-id 1
```

---

### 2. Events & Queries (`posthog events`)

#### `events query`
Execute a HogQL query or custom PostHog JSON query payload against events.

```bash
# Using HogQL string
aai-cli posthog events query --project-id 1 --query "SELECT event, count() FROM events GROUP BY event LIMIT 10"

# Using JSON query payload file
aai-cli posthog events query --project-id 1 --query-file ./query.json
```

Example response:
```json
{
  "columns": ["event", "count()"],
  "results": [
    ["$pageview", 1420],
    ["user_signed_up", 185]
  ],
  "types": ["String", "UInt64"]
}
```

---

### 3. Insights (`posthog insights`)

#### `insights list`
List team saved insights (trends, funnels, retention, paths, lifecycle).

```bash
aai-cli posthog insights list --project-id 1 [--limit N] [--offset N]
```

#### `insights get`
Get detailed definition and cached query result of a saved insight.

```bash
aai-cli posthog insights get <insight_id> --project-id 1
```

---

### 4. Persons & User Profiles (`posthog persons`)

#### `persons list`
List person profiles tracked in PostHog.

```bash
aai-cli posthog persons list --project-id 1 [--limit N] [--offset N]
```

#### `persons get`
Get details and properties of a specific person profile.

```bash
aai-cli posthog persons get <person_id> --project-id 1
```

---

### 5. Cohorts (`posthog cohorts`)

#### `cohorts list`
List user cohorts defined in the PostHog project.

```bash
aai-cli posthog cohorts list --project-id 1 [--limit N] [--offset N]
```

#### `cohorts get`
Get definition rules and count of a user cohort.

```bash
aai-cli posthog cohorts get <cohort_id> --project-id 1
```

---

### 6. Dashboards (`posthog dashboards`)

#### `dashboards list`
List team dashboards created in PostHog.

```bash
aai-cli posthog dashboards list --project-id 1 [--limit N] [--offset N]
```

#### `dashboards get`
Fetch dashboard items and tiles.

```bash
aai-cli posthog dashboards get <dashboard_id> --project-id 1
```

---

### 7. Annotations (`posthog annotations`)

#### `annotations list`
List release markers and experiment annotations.

```bash
aai-cli posthog annotations list --project-id 1 [--limit N] [--offset N]
```

#### `annotations get`
Fetch annotation details.

```bash
aai-cli posthog annotations get <annotation_id> --project-id 1
```

---

## Error response shape

All errors print to stderr as a single JSON line:

```json
{"code":"auth_error","details":{"attr":null,"code":"authentication_failed","detail":"Personal API key found in request Authorization header is invalid.","type":"authentication_error"},"message":"provider returned HTTP 401","operation":"projects.list","service":"posthog","status":401}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag (`--project-id`, `--query`) was missing or file unreadable |
| `config_error` | Missing profile, `POSTHOG_API_KEY`, or `POSTHOG_PROJECT_ID` |
| `auth_error` | HTTP 401/403 invalid API key or insufficient permissions |
| `not_found` | Resource ID not found |
| `provider_api_error` | PostHog API returned HTTP error |
