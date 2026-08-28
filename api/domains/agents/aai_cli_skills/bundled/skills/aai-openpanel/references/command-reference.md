# aai-cli OpenPanel Skill

Agent reference for the `aai-cli openpanel` command group.

## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile

OpenPanel profiles use a client ID/secret pair, sent as `openpanel-client-id` / `openpanel-client-secret` headers — not a bearer token:

```toml
[profiles.openpanel-read]
provider = "openpanel"
auth_type = "openpanel_client_credentials"
client_id = "018f0000-0000-0000-0000-000000000000"
api_token_secret = "openpanel-read.secret"
project_id = "proj_abc123"
```

`base_url` defaults to `https://api.openpanel.dev` and rarely needs overriding. `project_id` is optional on the profile — set it to avoid passing `--project-id` on every `insights`/`profiles` call.

**Client type is the most common failure mode.** OpenPanel clients are typed `write`, `read`, or `root` in the dashboard (Settings → Clients). A project's default client is `write`-only and will fail every command below with `401`/`403`. You need at least a `read` client (covers `events`, `insights`, `profiles`); `projects list`/`get` additionally require a `root` client specifically. It's common to configure two profiles against the same project: one `root` profile for `projects`, one `read` profile for everything else.

## Response shapes

Successful command output is JSON on stdout, always wrapped with an `_aai` pagination-metadata block from this CLI (not part of the raw OpenPanel response):

```json
{
  "_aai": {
    "pagination": {
      "continuation": null,
      "has_more": true,
      "instruction": "Run next_command to retrieve more results.",
      "next_command": "aai-cli openpanel events export --project-id proj_abc123 --limit 6",
      "returned_count": 3,
      "status": "more_available"
    }
  },
  "...": "rest of the provider response"
}
```

OpenPanel returns no continuation marker on any endpoint, so `status` is `more_available` only on `events export` (which knows `meta.totalCount`); every other list command reports `status: "unknown"` with a `next_command` that just retries at a larger `--limit`, and single-object commands report `not_applicable`.

**`projects list`** and **`projects get`** return the Manage API's raw shape: `{ "data": [...] }` or `{ "data": {...} }`.

**`events export`** returns `{ "meta": { "count", "totalCount", "pages", "current" }, "data": [...], "has_more": bool }`. This CLI paginates internally — `--limit` means "total rows wanted" (default 50), not a page size. It loops the provider's `page`/`limit` (per-page capped at 1000 by the provider) until enough rows are collected or the provider runs out, then reports `has_more` based on `meta.totalCount`.

Because the page size is `min(--limit, 1000)`, the loop only makes more than one provider call when `--limit` exceeds 1000 — verified live at `--limit 1100` on a 1062-event project: two calls, `meta.current: 2`, 1062 rows, `has_more: false`, ~2s. `meta.pages` is `ceil(totalCount / page size)`, so it moves with `--limit` (1062 events reported `pages: 1062` at `--limit 1`, `pages: 2` at `--limit 1100`) — it is not a stable provider page count.

OpenPanel also synthesizes `session_start`/`session_end` events server-side. They appear in unfiltered `events export` output and in `meta.totalCount`, so an unfiltered count is always higher than the number of events actually tracked; filter with `--event` when counting real events.

**`insights metrics`** returns `{ "metrics": {...}, "series": [...] }` — a summary object (`total_screen_views`, `total_sessions`, `unique_visitors`, `bounce_rate`, `avg_session_duration`, `views_per_session`, `total_revenue`) plus one `series` entry per bucket in range with the same fields, zero-filled for buckets with no traffic. The bucket is a **day** for multi-day ranges and an **hour** when `--start-date` equals `--end-date` (24 rows). Hourly labels end in `Z` but carry the workspace's timezone offset — live events stamped `14:34Z` landed in the `17:00:00.000Z` bucket (+3h), so don't read the label as UTC.

Adding `--filters` to `insights metrics` changes the shape, not just the numbers: `series` rows gain `overall_bounce_rate`/`overall_total_sessions`/`overall_unique_visitors` (`null` on zero-traffic buckets), drop the duplicated `_avg_session_duration`, and `avg_session_duration` returns on a different scale entirely (`161880` filtered vs `6.32` unfiltered for the same window). Filtered `unique_visitors` can also exceed `total_sessions` (13 vs 9 live). Read filtered metrics as event-scoped counts and don't compare their durations against unfiltered ones.

**`insights pages`** returns `{ "results": [...] }`, each row shaped `{ "path", "pageviews", "sessions", "revenue", "origin" }`. **`referrers`/`devices`/`geo`** return the same envelope with rows shaped `{ "name", "pageviews", "sessions", "revenue" }` — `name` holds whatever dimension value `--breakdown` selected (a referrer name, device type, browser, country code, etc.), not a field literally called `referrer_name`/`device`/`country`. `pages`, `referrers`, `devices`, and `geo` all accept `--cursor`/`--limit`/`--filters` — they use OpenPanel's older per-dimension routes (`/insights/:projectId/{column}`) rather than the newer unpaginated `/insights/:projectId/traffic/*` routes, because only the older routes accept those parameters at all.

**Breakdown rows come back unsorted — verified against a live workspace.** Despite the "top pages/referrers/…" framing, the provider applies no ordering the caller can rely on: a live `insights pages` run returned pageviews `11, 13, 10, 9, 9, 9, 7, 7` (ordered by `sessions`, not `pageviews`), and `insights geo`/`devices` rows were ordered by neither. Combined with the ignored `--limit` below, "top N" means: fetch all rows, sort client-side, then slice.

**`--limit` and `--cursor` are sent but not honored on `pages`/`referrers`/`devices`/`geo` — verified against a live workspace.** The CLI puts both on the query string, and the provider ignores them: `insights geo --limit 1` and `--limit 3` each returned the same 8 rows, and `--cursor` shifted nothing. Treat these four commands as returning **every** breakdown row for the date range, and slice client-side if you need fewer. Only `events export` paginates for real. `--filters` does work.

**Aggregation lag is dimension-dependent — verified against a live workspace.** `events export` and `insights pages` reflect newly tracked events within seconds, keyed off each event's real timestamp (including a backdated one supplied via the tracking SDK's `__timestamp` property). `insights metrics`, `referrers`, `devices`, and `geo`, by contrast, are driven by a session-aggregation pipeline that only picked up events tracked with their *actual* wall-clock send time in this test — events sent with a backdated `__timestamp` (days in the past) never appeared in those four endpoints, even minutes later, while `events export` and `pages` showed them immediately. If `insights metrics`/`referrers`/`devices`/`geo` look empty or thin right after a batch of events lands, don't assume the CLI or the date range is wrong — check whether `events export` for the same range/project shows the data; a mismatch there points at this pipeline lag rather than a request bug.

**`profiles list`** returns `{ "results": [...] }`, each a rich profile object (`id`, `email`/`first_name`/`last_name` if identified via `identify`, `created_at`, `last_seen_at`, and a `properties` object carrying whatever device/geo/referrer fields were captured on that profile's most recent event — `country`, `city`, `device`, `browser`, `os`, `latitude`/`longitude`, `referrer_name`, etc.). No cursor — `--limit` caps at 100 server-side; there is no way to page past 100 matches through this endpoint.

**`profiles get`** returns `{ "profile": {...}, "recentEvents": [...] }` — the profile object (same shape as one `profiles list` row) plus up to `--event-limit` of its most recent raw events (richer than `events export` rows: includes `duration`, `revenue`, `referrer`/`referrer_name`/`referrer_type`, lat/long, etc.).

## Error response shape

All errors print to stderr as a single JSON line:

```json
{"code":"auth_error","details":{"error":"Unauthorized","message":"Export: Client is not allowed to export"},"message":"provider returned HTTP 401","operation":"insights.metrics","service":"openpanel","status":401}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag or argument was missing (e.g. no `--project-id` and no `profile.project_id`) |
| `config_error` | Missing or malformed config, profile, or client credential setting |
| `auth_error` | Missing client_id/client_secret, or provider 401/403 — usually the wrong client type (see Profile above) |
| `not_found` | Provider returned 404 — an unknown project ID, or a bad path passed to `request` |
| `rate_limited` | Provider returned 429 |
| `provider_api_error` | Any other 4xx/5xx from OpenPanel |
| `internal_error` | Local request, response, or IO failure |

Exit codes: `2` invalid_input, `3` config_error/auth_error, `4` provider_api_error, `5` not_found, `6` rate_limited, `1` anything else. All verified live.

A `write`-typed client fails with `auth_error` at **HTTP 401** (`"Export: Client is not allowed to export"`), not the 403 the wrong-client-type failure mode might suggest — match on the `auth_error` code rather than the status. A non-`root` client on `projects list`/`get` fails the same way, with `"Manage: Only root clients are allowed to manage resources"`.

A bad `--project-id` surfaces three different ways, all verified live — don't write recovery logic that expects one:

| Command | Unknown project ID |
|---|---|
| `projects get`, `events export` | `not_found`, HTTP 404, exit 5 |
| `insights *`, `profiles list` | `provider_api_error`, HTTP **500** `"Internal server error"`, exit 4 |
| `profiles get` (unknown profile, valid project) | `not_found`, HTTP 404, exit 5, with `details.profileId` echoed back |

A real-but-empty project is different again: `insights metrics` returns a fully zero-filled `metrics`/`series`, `events export` returns `{"meta":{"count":0,...},"data":[]}` with `status: "complete"`, and `profiles list` returns `{"results":[]}` — all exit 0.

## Resources

- [Projects](#projects) — `projects list`, `projects get` (requires a `root` client)
- [Events](#events) — `events export`
- [Insights](#insights) — `insights metrics`, `pages`, `referrers`, `devices`, `geo`
- [Profiles](#profiles) — `profiles list`, `profiles get`
- [Request](#request) — `openpanel request` for uncommon endpoints

---

## Projects

Commands under `aai-cli openpanel projects`. Requires a `root` client profile.

### projects list

List every project in the client's organization.

```
aai-cli openpanel projects list --profile openpanel-root
```

```json
{
  "data": [
    {
      "id": "aai-cli-test",
      "name": "aai-cli-test",
      "organizationId": "open-panel-9164",
      "domain": "https://aai-cli-test.example.com",
      "cors": ["https://aai-cli-test.example.com"],
      "eventsCount": 29,
      "crossDomain": false,
      "allowUnsafeRevenueTracking": false,
      "filters": [],
      "types": [],
      "createdAt": "2026-08-12T14:50:16.053Z",
      "updatedAt": "2026-08-12T16:03:51.279Z",
      "deleteAt": null
    }
  ]
}
```

The `id` field is the `project_id` used by every `insights`/`profiles`/`events` command. `eventsCount` is a materialized counter — it can lag a few minutes behind what `events export`/`insights pages` already show for freshly tracked events.

### projects get

Get a single project by ID.

```
aai-cli openpanel projects get <PROJECT_ID> --profile openpanel-root
```

| Argument | Required | Description |
|---|---|---|
| `PROJECT_ID` | **yes** | The project ID (from `projects list`) |

```json
{ "data": { "id": "aai-cli-test", "name": "aai-cli-test", "domain": "https://aai-cli-test.example.com", "eventsCount": 29 } }
```

---

## Events

Commands under `aai-cli openpanel events`. Requires a `read` or `root` client profile.

### events export

Export a paginated list of raw tracked events.

```
aai-cli openpanel events export [--project-id ID] [--event NAME]... [--profile-id ID]
                                 [--start DATE] [--end DATE] [--limit N]
                                 [--includes profile,meta] [--filters JSON]
                                 --profile openpanel-read
```

| Flag | Required | Description |
|---|---|---|
| `--project-id` | conditional | Required unless the client is already scoped to one project |
| `--event` | no | Event name to filter by; repeat for multiple names |
| `--profile-id` | no | Restrict to a single visitor profile |
| `--start` / `--end` | no | Inclusive range, any format accepted by the JS `Date` constructor (e.g. `2024-01-01`) |
| `--limit` | no | Total events wanted across pages (default `50`) |
| `--includes` | no | Comma-separated extra data to attach: `profile`, `meta` |
| `--filters` | no | JSON array of provider chart-event filters, passed through as-is |

**Example**

```
aai-cli openpanel events export --project-id proj_abc123 --event page_view --limit 5 --profile openpanel-read
```

```json
{
  "meta": { "count": 1, "totalCount": 48, "pages": 16, "current": 1 },
  "data": [
    {
      "id": "11390ab5-e392-4a47-9e71-764c1bff8ca5",
      "name": "screen_view",
      "createdAt": "2026-08-12T20:48:37.602Z",
      "profileId": "visitor-108",
      "projectId": "aai-cli-test",
      "sessionId": "WEVQlYf09jo2B7DGgL5JbQ",
      "deviceId": "499cbd81257e58ee598aaae55f93cd00",
      "path": "/contact",
      "browser": "Mobile Safari",
      "os": "iOS",
      "country": "IN",
      "city": "",
      "groups": []
    }
  ],
  "has_more": true
}
```

Note there is no `properties` field on export rows in this shape — `__path` sent at track time surfaces as the top-level `path` column, and device/geo columns are derived from the request's `user-agent`/`x-client-ip`. Referrer and other custom properties are not included here; pass `--includes profile` to attach a nested `profile` object per row (whose `properties` carries `referrer`/`referrer_name`/`referrer_type`, lat/long, etc.), or use `profiles get` for the richer per-event shape.

The `profile` object attached by `--includes profile` uses **camelCase** keys (`createdAt`, `firstName`, `lastSeenAt`, `isExternal`, `projectId`), unlike the snake_case profile objects returned by `profiles list`/`profiles get` (`created_at`, `first_name`, …). The nested `properties` map stays snake_case in both.

`meta.totalCount` is scoped to the active filters, so it moves with `--event`: the same project reported `totalCount: 1062` unfiltered and `11` for `--event signup`. Repeating `--event` unions the names rather than intersecting them — `--event load_probe --event signup` reported `totalCount: 961` against 950 `load_probe` + 11 `signup` events.

`--includes profile` attaches the nested `profile` object described above. `--includes meta` is accepted (HTTP 200, exit 0) but attached no `meta` field to any row for events tracked through the HTTP `/track` API — don't build on it without checking your own data first.

`--limit 0` short-circuits to an empty result without calling the provider (`status: "complete"`, `meta.current: 0`).

---

## Insights

Commands under `aai-cli openpanel insights`. Requires a `read` or `root` client profile. Every action needs a project ID — pass `--project-id` or set `profile.project_id`.

Shared date-range flags on every `insights` command:

| Flag | Description |
|---|---|
| `--project-id` | Project to query. Falls back to `profile.project_id` |
| `--start-date` / `--end-date` | Explicit ISO date range |
| `--range` | Relative preset (e.g. `7d`, `30d`, `3m`), used when `--start-date` is omitted |
| `--filters` | JSON array of provider chart-event filters |

`pages`, `referrers`, `devices`, `geo` additionally accept:

| Flag | Default | Description |
|---|---|---|
| `--cursor` | none | Accepted and sent, but ignored by the provider — see above |
| `--limit` | `10` | Accepted and sent, but ignored by the provider — all rows come back regardless |

### insights metrics

Aggregated visitors, sessions, and bounce rate for a date range.

```
aai-cli openpanel insights metrics --project-id proj_abc123 --range 7d --profile openpanel-read
```

```json
{
  "metrics": {
    "total_screen_views": 23,
    "total_sessions": 9,
    "unique_visitors": 9,
    "bounce_rate": 11.11,
    "avg_session_duration": 1.74125,
    "views_per_session": 2.56,
    "total_revenue": 0
  },
  "series": [
    { "date": "2026-08-06T00:00:00.000Z", "total_screen_views": 0, "total_sessions": 0, "unique_visitors": 0, "bounce_rate": 0, "avg_session_duration": 0, "views_per_session": 0, "total_revenue": 0 },
    { "date": "2026-08-12T00:00:00.000Z", "total_screen_views": 23, "total_sessions": 9, "unique_visitors": 9, "bounce_rate": 11.11, "avg_session_duration": 1.74125, "views_per_session": 2.56, "total_revenue": 0 }
  ]
}
```

`series` has one entry per day in the requested range regardless of traffic — days with no matching sessions are zero-filled rather than omitted. Each `series` row also carries a redundant `_avg_session_duration` alongside `avg_session_duration` (same value); read the unprefixed one.

### insights pages

Top pages by pageviews for a date range.

```
aai-cli openpanel insights pages --project-id proj_abc123 --range 7d --limit 10 --profile openpanel-read
```

```json
{
  "results": [
    { "path": "/contact", "pageviews": 7, "sessions": 6, "revenue": 0, "origin": "" },
    { "path": "/about", "pageviews": 7, "sessions": 5, "revenue": 0, "origin": "" }
  ]
}
```

### insights referrers

Top referrer/UTM breakdown for a date range.

```
aai-cli openpanel insights referrers [--breakdown referrer-name|referrer|referrer-type|utm-source|utm-medium|utm-campaign|utm-term|utm-content]
                                      --project-id proj_abc123 --range 7d --profile openpanel-read
```

`--breakdown` (default `referrer-name`) maps to the provider's snake_case dimension name, e.g. `--breakdown utm-source` requests the `utm_source` breakdown column.

```json
{
  "results": [
    { "name": "Google", "pageviews": 6, "sessions": 3, "revenue": 0 },
    { "name": "Hacker News", "pageviews": 6, "sessions": 2, "revenue": 0 }
  ]
}
```

**A `null` `name` row is the "dimension absent" bucket, not an error and not an empty result.** Verified live on a workspace where three sessions carried UTM query parameters and eleven did not:

```json
{
  "results": [
    { "name": null, "pageviews": 43, "sessions": 14, "revenue": 0 },
    { "name": "newsletter", "pageviews": 3, "sessions": 1, "revenue": 0 },
    { "name": "twitter-ads", "pageviews": 3, "sessions": 1, "revenue": 0 },
    { "name": "product-hunt", "pageviews": 1, "sessions": 1, "revenue": 0 }
  ]
}
```

The `null` row aggregates all traffic that has no value for that dimension, so when *no* event carries the dimension (no UTM params anywhere, no resolvable device `model`, …) the response is a single `null` row holding the range totals. Filter out `name: null` before charting a breakdown, and don't read a lone `null` row as "the command failed".

UTM dimensions are populated from query parameters on the tracked path (`__path`, e.g. `/docs?utm_source=newsletter&utm_campaign=launch2026`), not from `__referrer`.

`--breakdown referrer-name` is not purely referrer-derived: OpenPanel folds `utm_source` values into it for sessions that arrived with UTM parameters and no referrer. The same live range returned `Google`, `Hacker News`, `GitHub`, `Twitter`, `Bing` **and** `newsletter`, `twitter-ads`, `product-hunt` in one `referrer-name` breakdown. Use `--breakdown referrer` (raw URL) when you need referrers only, and `--breakdown utm-source` for campaign attribution.

### insights devices

Top device/browser/OS breakdown for a date range.

```
aai-cli openpanel insights devices [--breakdown device|brand|model|browser|browser-version|os|os-version]
                                    --project-id proj_abc123 --range 7d --profile openpanel-read
```

`--breakdown` defaults to `device`.

```json
{
  "results": [
    { "name": "desktop", "pageviews": 17, "sessions": 6, "revenue": 0 },
    { "name": "mobile", "pageviews": 4, "sessions": 2, "revenue": 0 },
    { "name": "tablet", "pageviews": 2, "sessions": 1, "revenue": 0 }
  ]
}
```

`--breakdown brand`/`model` only carry values the provider can derive from the user agent, so unidentifiable desktop traffic collapses into the `name: null` bucket described under `referrers` — a live `--breakdown model` run returned `{ "name": null, "pageviews": 29, "sessions": 9 }`, then `Macintosh`, `iPhone`, `Pixel 8`, `iPad`.

### insights geo

Top country/region/city breakdown for a date range.

```
aai-cli openpanel insights geo [--breakdown country|region|city]
                                --project-id proj_abc123 --range 7d --profile openpanel-read
```

`--breakdown` defaults to `country`.

```json
{
  "results": [
    { "name": "US", "pageviews": 4, "sessions": 2, "revenue": 0 },
    { "name": "IN", "pageviews": 2, "sessions": 1, "revenue": 0 }
  ]
}
```

`--breakdown city` (and `region`) adds a `prefix` field holding the parent country code, and leaves `name` as `null` for any row whose city the provider could not resolve from the IP — so a city breakdown is typically a mix of real names and `null`s that still carry usable `prefix`/`pageviews`:

```json
{
  "results": [
    { "name": "Montreal", "prefix": "CA", "pageviews": 4, "sessions": 1, "revenue": 0 },
    { "name": null, "prefix": "US", "pageviews": 4, "sessions": 2, "revenue": 0 }
  ]
}
```

---

## Profiles

Commands under `aai-cli openpanel profiles`. Requires a `read` or `root` client profile.

### profiles list

Search and filter user profiles.

```
aai-cli openpanel profiles list [--project-id ID] [--name X] [--email X] [--country X] [--city X]
                                 [--device X] [--browser X] [--inactive-days N] [--min-sessions N]
                                 [--performed-event NAME] [--filters JSON]
                                 [--sort-order asc|desc] [--limit N]
                                 --profile openpanel-read
```

| Flag | Default | Description |
|---|---|---|
| `--project-id` | `profile.project_id` | Project to search. Required unless set on the profile |
| `--name` | — | Substring match against first/last name (`--name Grace` matched profile `Grace Hopper`) |
| `--email` | — | Match on the identified email address |
| `--country` | — | Two-letter country code from the profile's latest event (`US`, `DE`, …) |
| `--city` | — | City name as resolved from IP (`Montreal`) |
| `--device` | — | `desktop`, `mobile`, or `tablet` |
| `--browser` | — | Browser name as reported in `properties.browser` (`Chrome`, `Firefox`, `Mobile Safari`) |
| `--inactive-days` | — | Only profiles whose `last_seen_at` is at least N days old |
| `--min-sessions` | — | Only profiles with at least N sessions. Single-session visitors matched `1` and not `2` |
| `--performed-event` | — | Only profiles that fired the named event (e.g. `signup`) |
| `--filters` | — | JSON array of provider chart-event filters, passed through as-is |
| `--sort-order` | `desc` | `desc` returns the most recently created profiles first; `asc` flips it to oldest-first |
| `--limit` | `20` | Capped at `100` server-side; there is no cursor to page further |

All of these are provider-side filters — every one was exercised against a live workspace and narrowed the result set as described. They AND together: `--country US --device desktop` returned only US desktop profiles, and `--country US --device mobile` returned `{"results":[]}` (exit 0) on the same workspace.

**Example**

```
aai-cli openpanel profiles list --project-id proj_abc123 --limit 5 --profile openpanel-read
```

```json
{
  "results": [
    {
      "id": "visitor-101",
      "email": "ada@example.com",
      "first_name": "Ada",
      "last_name": "Lovelace",
      "created_at": "2026-08-12 20:48:13.000",
      "last_seen_at": "2026-08-12 20:48:14.000",
      "is_external": true,
      "avatar": "",
      "groups": [],
      "project_id": "aai-cli-test",
      "properties": {
        "country": "US",
        "device": "desktop",
        "browser": "Chrome",
        "os": "Windows",
        "path": "/pricing",
        "referrer_name": "Google",
        "latitude": "37.751",
        "longitude": "-97.822"
      }
    }
  ]
}
```

Anonymous profiles (no `identify` call) still show up with `email`/`first_name`/`last_name` as empty strings, not `null` or omitted.

### profiles get

Get a single profile with its most recent events.

```
aai-cli openpanel profiles get <PROFILE_ID> [--project-id ID] [--event-limit N] --profile openpanel-read
```

| Argument/Flag | Required | Default | Description |
|---|---|---|---|
| `PROFILE_ID` | **yes** | — | The profile ID (from `profiles list` or `events export`) |
| `--event-limit` | no | `20` | Number of recent events to include |

```json
{
  "profile": {
    "id": "visitor-108",
    "email": "alan@example.com",
    "first_name": "Alan",
    "last_name": "Turing",
    "created_at": "2026-08-12 20:48:35.000",
    "last_seen_at": "2026-08-12 20:48:36.000",
    "properties": { "country": "IN", "device": "tablet", "referrer_name": "Twitter" }
  },
  "recentEvents": [
    {
      "id": "11390ab5-e392-4a47-9e71-764c1bff8ca5",
      "name": "screen_view",
      "created_at": "2026-08-12 20:48:37.602",
      "profile_id": "visitor-108",
      "path": "/contact",
      "referrer": "https://twitter.com",
      "referrer_name": "Twitter",
      "referrer_type": "social",
      "duration": 0,
      "revenue": 0,
      "session_id": "WEVQlYf09jo2B7DGgL5JbQ"
    }
  ]
}
```

The top-level shape is `{ "profile", "recentEvents" }`, not a flat profile-with-`events` object — `recentEvents` rows are richer than `events export` rows (they include `duration`, `revenue`, and referrer fields directly).

---

## Request

For uncommon OpenPanel endpoints not covered by typed commands:

```
aai-cli openpanel request get /export/events --query projectId=proj_abc123 --query limit=1
aai-cli openpanel request get /manage/projects
```

Sends the request with profile authentication against `openpanel_base` (default `https://api.openpanel.dev`). `--json` (inline or a file path, `-` for stdin) sets the request body; `--allow-write` is required for `post`/`put`/`patch`/`delete` — but OpenPanel exposes no write endpoints in this integration's supported surface, so `request` is effectively `get`/`head` only in practice. Returns the raw provider response.
