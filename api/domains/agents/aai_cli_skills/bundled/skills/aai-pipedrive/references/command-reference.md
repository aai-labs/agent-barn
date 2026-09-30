# aai-cli Pipedrive Skill

Agent reference for the `aai-cli pipedrive` command group.

## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile

Pipedrive profiles use a personal API token:

```toml
[profiles.pipedrive-work]
provider = "pipedrive"
auth_type = "pipedrive_personal_token"
api_token_secret = "pipedrive.token"
```

`base_url` defaults to `https://api.pipedrive.com` and rarely needs overriding.

## Response shapes

Successful command output is JSON on stdout, always wrapped with an `_aai` pagination-metadata block from this CLI (not part of the raw Pipedrive response):

```json
{
  "_aai": {
    "pagination": {
      "continuation": null,
      "has_more": false,
      "instruction": "...",
      "next_command": "...",
      "returned_count": 3,
      "status": "complete"
    }
  },
  "...": "rest of the provider response"
}
```

**Get / single-record commands** (`get`, `create`, `update`, `delete`) return the raw Pipedrive response, typically `{ "success": true, "data": {...} }`.

**List commands** aggregate Pipedrive pages up to `--limit` and return the raw provider list shape, `{ "success": true, "data": [...], "additional_data": {...} }`. Internally this CLI uses two pagination styles depending on Pipedrive API version:
- v1 endpoints (`leads`, `notes`, `mailbox`, `deals flow`) paginate via `start`/`limit`, surfaced in `additional_data.pagination`.
- v2 endpoints (`persons`, `organizations`, `deals`, `activities` list/search) paginate via cursor, surfaced in `additional_data.next_cursor`.

**Search commands** return Pipedrive's search-result envelope: `{ "success": true, "data": { "items": [{ "item": {...}, "result_score": N }] } }`.

**View commands** (`deals view`, `persons view`, `organizations view`) return a composed object, not a raw Pipedrive shape:

```json
{ "record": {...}, "activities": {...}, "notes": {...}, "mail_messages": {...} }
```

`mail_messages` is only present when `--include-mail` is passed.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{"code":"not_found","details":{"code":"ERR_NOT_FOUND","error":"Deal not found","success":false},"message":"provider returned HTTP 404","operation":"deals.get","service":"pipedrive","status":404}
```

| Code | Meaning |
|---|---|
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `config_error` | Missing or malformed config, profile, or token setting |
| `auth_error` | Missing credentials, invalid token, or provider 401/403 |
| `not_found` | Provider returned 404 |
| `rate_limited` | Provider returned 429 |
| `provider_api_error` | Provider returned another 4xx/5xx |
| `internal_error` | Local request, response, or IO failure |

Exit code is non-zero on any error.

## Resources

- [Leads](#leads) — `leads list`, `search`, `get`, `create`, `update`, `delete`, `convert`
- [Persons](#persons) — `persons list`, `search`, `get`, `view`, `activities`, `notes`, `mail-messages`, `create`, `update`, `delete`
- [Organizations](#organizations) — same shape as persons
- [Deals](#deals) — `deals list`, `search`, `get`, `view`, `activities`, `notes`, `mail-messages`, `flow`, `create`, `update`, `delete`
- [Labels](#labels) — `labels leads list/create/update/delete`, `labels deals|persons|organizations list`
- [Activities](#activities) — `activities list`, `get` (cross-record)
- [Notes](#notes) — `notes list`, `get` (cross-record)
- [Mailbox](#mailbox) — `mailbox messages get`, `mailbox threads list/get/messages`
- [Request](#request) — `pipedrive request` for uncommon endpoints

## Leads

Commands under `aai-cli pipedrive leads`. Lead IDs are UUIDs, not integers.

### leads list

```
aai-cli pipedrive leads list [--limit N] [--owner-id ID] [--person-id ID]
                              [--organization-id ID] [--filter-id ID]
                              [--updated-since TS] [--sort FIELD] [--archived]
```

`--archived` switches from `/v1/leads` to `/v1/leads/archived`.

**Example**

```json
{
  "data": [
    {
      "add_time": "2026-07-28T08:46:18.313Z",
      "cc_email": "testcomp+15932737+leadc4jorb9joh4mcjuzuf5571dgf@pipedrivemail.com",
      "id": "ccd3eb90-8a60-11f1-9a3f-0fd442a4a55f",
      "is_archived": false,
      "label_ids": [],
      "organization_id": 3,
      "owner_id": 27007993,
      "person_id": 3,
      "source_name": "API",
      "title": "Skill Doc Test Lead",
      "value": null,
      "visible_to": "3",
      "was_seen": false
    }
  ],
  "success": true
}
```

### leads search

```
aai-cli pipedrive leads search --term TEXT [--fields LIST] [--exact-match]
                                [--person-id ID] [--organization-id ID] [--limit N]
```

**Example** (search-result envelope, note the nested `item`/`result_score`)

```json
{
  "data": {
    "items": [
      {
        "item": {
          "id": "ccd3eb90-8a60-11f1-9a3f-0fd442a4a55f",
          "organization": { "id": 3, "name": "Skill Doc Test Org" },
          "person": { "id": 3, "name": "Skill Doc Test Person" },
          "title": "Skill Doc Test Lead",
          "type": "lead"
        },
        "result_score": 0.99348
      }
    ]
  },
  "success": true
}
```

### leads get / create / update / delete

```
aai-cli pipedrive leads get <lead-id>
aai-cli pipedrive leads create [--json JSON_OR_PATH] --title TEXT
                                [--person-id ID] [--organization-id ID] [--label-ids CSV]
aai-cli pipedrive leads update <lead-id> [--json JSON_OR_PATH] [--title TEXT]
                                [--person-id ID] [--organization-id ID] [--label-ids CSV]
aai-cli pipedrive leads delete <lead-id>
```

`get`/`create`/`update` return the same single-record shape as `leads list` items (unwrapped, not the search `item` wrapper). `delete` returns `{ "data": { "id": "<lead-id>" }, "success": true }`.

### leads convert

Converts a lead into a deal.

```
aai-cli pipedrive leads convert <lead-id> [--json JSON_OR_PATH]
```

Calls `POST /api/v2/leads/{id}/convert/deal`. `--json` can pass a body (e.g. `{"pipeline_id": 2}`); omit for provider defaults.

## Persons

Commands under `aai-cli pipedrive persons`.

### persons list

```
aai-cli pipedrive persons list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID]
                                [--org-id ID] [--deal-id ID] [--updated-since TS]
                                [--updated-until TS] [--sort-by FIELD]
                                [--sort-direction asc|desc] [--include-labels]
```

**Example**

```json
{
  "data": [
    {
      "emails": [{ "label": "work", "primary": true, "value": "mark.evans@axiomtelecom.com" }],
      "id": 1,
      "name": "[Sample] Mark Evans",
      "org_id": 2,
      "phones": [{ "label": "", "primary": true, "value": "737-555-0763" }]
    }
  ],
  "success": true
}
```

### persons search

```
aai-cli pipedrive persons search --term TEXT [--fields LIST] [--exact-match]
                                  [--organization-id ID] [--limit N]
```

Same search envelope as `leads search` (`data.items[].item`, `result_score`).

### persons get / view

```
aai-cli pipedrive persons get <person-id> [--include-labels]
aai-cli pipedrive persons view <person-id> [--limit N] [--include-labels] [--include-mail]
```

`get` returns one record. `view` returns `{ record, activities, notes, mail_messages? }`:

```json
{
  "activities": { "data": [ { "id": 3, "subject": "[Sample] Cloud migration roadmap review with Mark", "type": "meeting", "deal_id": 2, "person_id": 1 } ], "success": true },
  "notes": { "data": [ { "id": 1, "content": "[Sample] Mark wants migration done before Series B closes in Q4. Hard deadline.", "deal_id": 2, "person_id": 1 } ], "success": true },
  "record": { "id": 1, "name": "[Sample] Mark Evans", "org_id": 2 }
}
```

### persons activities / notes / mail-messages

List records associated with a person (same shape as the standalone `activities list --person-id` / `notes list --person-id` / mailbox lookups, pre-filtered).

```
aai-cli pipedrive persons activities <person-id> [--limit N]
aai-cli pipedrive persons notes <person-id> [--limit N]
aai-cli pipedrive persons mail-messages <person-id> [--limit N]
```

### persons create / update / delete

```
aai-cli pipedrive persons create [--json JSON_OR_PATH] --name TEXT
                                  [--org-id ID] [--email TEXT] [--phone TEXT] [--label-ids CSV]
aai-cli pipedrive persons update <person-id> [--json JSON_OR_PATH] [--name TEXT]
                                  [--org-id ID] [--email TEXT] [--phone TEXT] [--label-ids CSV]
aai-cli pipedrive persons delete <person-id>
```

**Example** (`persons create --name "Skill Doc Test Person" --email skilldoc@example.com --phone 555-0100`)

```json
{
  "data": {
    "add_time": "2026-07-28T08:46:03Z",
    "emails": [{ "label": "work", "primary": true, "value": "skilldoc@example.com" }],
    "first_name": "Skill Doc Test",
    "id": 3,
    "last_name": "Person",
    "name": "Skill Doc Test Person",
    "org_id": null,
    "phones": [{ "label": "work", "primary": true, "value": "555-0100" }]
  },
  "success": true
}
```

`delete` returns `{ "data": { "id": <id> }, "success": true }`.

## Organizations

Commands under `aai-cli pipedrive organizations`. Same shape as [Persons](#persons), minus `email`/`phone` — organizations use `--name` and `--address` instead.

```
aai-cli pipedrive organizations list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID]
                                      [--updated-since TS] [--updated-until TS] [--sort-by FIELD]
                                      [--sort-direction asc|desc] [--include-labels]
aai-cli pipedrive organizations search --term TEXT [--fields LIST] [--exact-match] [--limit N]
aai-cli pipedrive organizations get <org-id> [--include-labels]
aai-cli pipedrive organizations view <org-id> [--limit N] [--include-labels] [--include-mail]
aai-cli pipedrive organizations activities <org-id> [--limit N]
aai-cli pipedrive organizations notes <org-id> [--limit N]
aai-cli pipedrive organizations mail-messages <org-id> [--limit N]
aai-cli pipedrive organizations create [--json JSON_OR_PATH] --name TEXT [--address TEXT] [--label-ids CSV]
aai-cli pipedrive organizations update <org-id> [--json JSON_OR_PATH] [--name TEXT] [--address TEXT] [--label-ids CSV]
aai-cli pipedrive organizations delete <org-id>
```

**Example** (`organizations get`)

```json
{
  "data": {
    "address": null,
    "id": 3,
    "name": "Skill Doc Test Org",
    "owner_id": 27007993,
    "website": null
  },
  "success": true
}
```

Note: in a live test, `--address` on `create` did not persist (`address` came back `null`) — Pipedrive's v2 organization address field may require a structured object rather than a plain string via this flag. Verify with `organizations get` after create if the address matters.

## Deals

Commands under `aai-cli pipedrive deals`.

### deals list / search / get / view

```
aai-cli pipedrive deals list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID]
                              [--person-id ID] [--org-id ID] [--pipeline-id ID] [--stage-id ID]
                              [--status open|won|lost|deleted] [--updated-since TS]
                              [--updated-until TS] [--sort-by FIELD] [--sort-direction asc|desc]
                              [--include-labels]
aai-cli pipedrive deals search --term TEXT [--fields LIST] [--exact-match] [--person-id ID]
                                [--organization-id ID] [--status open|won|lost] [--limit N]
aai-cli pipedrive deals get <deal-id> [--include-labels]
aai-cli pipedrive deals view <deal-id> [--limit N] [--include-labels] [--include-mail]
```

**Example** (`deals get --include-labels`)

```json
{
  "data": {
    "currency": "USD",
    "id": 3,
    "label_ids": [],
    "labels": [],
    "org_id": 3,
    "person_id": 3,
    "pipeline_id": 2,
    "stage_id": 6,
    "status": "open",
    "title": "Skill Doc Test Deal",
    "value": 5000.0
  },
  "success": true
}
```

**Example** (`deals search --status open`, search envelope includes resolved `stage`/`organization`/`person` names)

```json
{
  "data": {
    "items": [
      {
        "item": {
          "id": 3,
          "organization": { "id": 3, "name": "Skill Doc Test Org" },
          "person": { "id": 3, "name": "Skill Doc Test Person" },
          "stage": { "id": 6, "name": "Qualified" },
          "status": "open",
          "title": "Skill Doc Test Deal",
          "value": 5000
        },
        "result_score": 1.092828
      }
    ]
  },
  "success": true
}
```

### deals activities / notes / mail-messages

Same pattern as [persons activities/notes/mail-messages](#persons-activities--notes--mail-messages), filtered by `deal_id`.

```
aai-cli pipedrive deals activities <deal-id> [--limit N]
aai-cli pipedrive deals notes <deal-id> [--limit N]
aai-cli pipedrive deals mail-messages <deal-id> [--limit N]
```

### deals flow

List updates about a deal, including stage transitions. Wraps Pipedrive's `GET /v1/deals/{id}/flow`.

```
aai-cli pipedrive deals flow <deal-id> [--limit N]
```

Returns a mixed feed of `activity`, `note`, and `dealChange` entries (v1 `start`/`limit` pagination). **Stage transitions appear as `dealChange` entries with `data.field_key == "stage_id"`** — `old_value`/`new_value` are stage IDs, and `additional_data.old_value_formatted`/`new_value_formatted` give human-readable stage names.

**Example** (real stage transition captured live: deal moved "Negotiations" → "Contract Signed")

```json
{
  "data": [
    {
      "object": "activity",
      "timestamp": "2026-07-29 00:00:00",
      "data": { "id": 2, "deal_id": 1, "type": "email", "subject": "[Sample] Send revised contract with 24/7 support tier pricing" }
    },
    {
      "object": "dealChange",
      "timestamp": "2026-07-28 08:05:56",
      "data": {
        "id": 3,
        "item_id": 1,
        "field_key": "stage_id",
        "old_value": "10",
        "new_value": "11",
        "additional_data": { "old_value_formatted": "Negotiations", "new_value_formatted": "Contract Signed" },
        "log_time": "2026-07-28 08:05:56",
        "change_source": "app"
      }
    },
    {
      "object": "note",
      "timestamp": "2026-07-28 07:51:29",
      "data": { "id": 2, "deal_id": 1, "content": "[Sample] Nina is frustrated with their current provider — slow response times. Ready to switch." }
    },
    {
      "object": "dealChange",
      "timestamp": "2026-07-28 07:51:28",
      "data": { "id": 1, "item_id": 1, "field_key": "add_time", "old_value": null, "new_value": "2026-07-28 07:51:28" }
    }
  ],
  "additional_data": { "pagination": { "start": 0, "limit": 20, "more_items_in_collection": false } },
  "success": true
}
```

### deals create / update / delete

```
aai-cli pipedrive deals create [--json JSON_OR_PATH] --title TEXT [--person-id ID] [--org-id ID]
                                [--value NUM] [--currency CODE] [--pipeline-id ID] [--stage-id ID] [--label-ids CSV]
aai-cli pipedrive deals update <deal-id> [--json JSON_OR_PATH] [--title TEXT] [--person-id ID]
                                [--org-id ID] [--value NUM] [--currency CODE] [--pipeline-id ID]
                                [--stage-id ID] [--label-ids CSV]
aai-cli pipedrive deals delete <deal-id>
```

**Example** (`deals create --title "Skill Doc Test Deal" --person-id 3 --org-id 3 --value 5000 --currency USD`)

```json
{
  "data": {
    "currency": "USD",
    "id": 3,
    "org_id": 3,
    "person_id": 3,
    "pipeline_id": 2,
    "stage_id": 6,
    "status": "open",
    "title": "Skill Doc Test Deal",
    "value": 5000.0
  },
  "success": true
}
```

Note: `pipeline_id`/`stage_id` default to the account's default pipeline/first stage when omitted — set `--stage-id` explicitly if the deal needs a specific starting stage.

## Labels

Commands under `aai-cli pipedrive labels`. Lead labels are a real CRUD resource; deal/person/organization "labels" are read-only custom-field option lists (`labels deals|persons|organizations list` — `create`/`update`/`delete` are not exposed for these, manage them from the Pipedrive UI's field settings).

### labels leads list / create / update / delete

```
aai-cli pipedrive labels leads list
aai-cli pipedrive labels leads create --name TEXT --color COLOR
aai-cli pipedrive labels leads update <label-id> [--name TEXT] [--color COLOR]
aai-cli pipedrive labels leads delete <label-id>
```

**Example** (`labels leads list`)

```json
{
  "data": [
    { "color": "red", "id": "df8cc000-2770-4ffd-a248-4ab513a65f3f", "name": "Hot" },
    { "color": "yellow", "id": "4e2c6d6a-0350-4092-a859-4ca91befb2e2", "name": "Warm" },
    { "color": "blue", "id": "b4abba40-167c-476a-a7df-4a91933f783e", "name": "Cold" }
  ],
  "success": true
}
```

### labels deals / persons / organizations list

```
aai-cli pipedrive labels deals list
aai-cli pipedrive labels persons list
aai-cli pipedrive labels organizations list
```

Reads the label options from the corresponding field definition (e.g. `/api/v2/dealFields`). Returns `{ "data": [], "success": true }` when the account has no label field configured for that resource yet — an empty array is a valid, non-error response.

## Activities

Commands under `aai-cli pipedrive activities`. Cross-record — use `--deal-id`/`--person-id`/`--org-id`/`--lead-id` to scope. There is no `create`/`update`/`delete`; activities are read-only from this CLI's current slice.

```
aai-cli pipedrive activities list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID]
                                   [--deal-id ID] [--lead-id ID] [--person-id ID] [--org-id ID]
                                   [--done true|false] [--updated-since TS] [--updated-until TS]
                                   [--sort-by FIELD] [--sort-direction asc|desc] [--include-attendees]
aai-cli pipedrive activities get <activity-id>
```

**Example** (`activities get`)

```json
{
  "data": {
    "deal_id": 1,
    "done": false,
    "due_date": "2026-07-28",
    "id": 1,
    "person_id": 2,
    "subject": "[Sample] Review SLA terms with Nina",
    "type": "call"
  },
  "success": true
}
```

## Notes

Commands under `aai-cli pipedrive notes`. Cross-record — use `--deal-id`/`--person-id`/`--org-id`/`--lead-id` to scope. There is no `create`/`update`/`delete` at this level (use record-scoped associations, or `pipedrive request` for the raw v1 note-write endpoints if needed).

```
aai-cli pipedrive notes list [--limit N] [--user-id ID] [--lead-id ID] [--deal-id ID]
                              [--person-id ID] [--org-id ID] [--sort FIELD]
                              [--start-date DATE] [--end-date DATE] [--updated-since TS]
aai-cli pipedrive notes get <note-id>
```

**Example** (`notes get`)

```json
{
  "data": {
    "content": "[Sample] Nina is frustrated with their current provider — slow response times. Ready to switch.",
    "deal": { "title": "[Sample] Managed IT Support Contract" },
    "deal_id": 1,
    "id": 2,
    "person": { "name": "[Sample] Nina Patel" },
    "user": { "email": "samibre121@gmail.com", "is_you": true, "name": "Samuel Birhanu" }
  },
  "success": true
}
```

## Mailbox

Commands under `aai-cli pipedrive mailbox`. Requires a synced Pipedrive mailbox (Smart Email / BCC or full sync). Returns empty results (not an error) when no mailbox is connected to the account.

```
aai-cli pipedrive mailbox messages get <message-id> [--include-body]
aai-cli pipedrive mailbox threads list [--folder inbox|drafts|sent|archive] [--limit N]
aai-cli pipedrive mailbox threads get <thread-id>
aai-cli pipedrive mailbox threads messages <thread-id>
```

**Example** (`mailbox threads list --folder inbox`, live account with no synced mailbox)

```json
{
  "data": [],
  "additional_data": { "pagination": { "count": 0, "limit": 50, "more_items_in_collection": false, "start": 0 } },
  "success": true
}
```

## Request

For uncommon Pipedrive REST endpoints not covered by typed commands (e.g. pipelines, stages, custom fields metadata, filters):

```
aai-cli pipedrive request get /api/v2/pipelines
aai-cli pipedrive request get /v1/dealFields
aai-cli pipedrive request post /api/v2/deals/123/followers --json '{"user_id": 27007993}'
```

Sends the request with profile authentication against `pipedrive_base` (default `https://api.pipedrive.com`). Returns the raw provider response.
