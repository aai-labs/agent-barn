"""aai-cli pipedrive skill docs."""

PIPEDRIVE_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/pipedrive_skill.md",
        "skill_content": """\
# aai-cli Pipedrive Skill

Agent reference for the `aai-cli pipedrive` command group. Covers leads, persons,
organizations, deals, labels, activities, notes, and synced email history.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, API
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flag

Every command requires `--profile pipedrive-work`. Always include it.

```
aai-cli pipedrive <resource> <verb> --profile pipedrive-work [other flags]
```

A Pipedrive personal API token grants full account access — there are no scopes to
select or worry about. Some accounts also configure a company-specific domain instead
of the default `api.pipedrive.com` endpoint; either way the `--profile` flag is all you
need to pass, the endpoint is already resolved on disk.

## Response shapes

Pipedrive's API wraps every response in an envelope: `{"success": true, "data": ...}`.

**List commands** return `data` as an array, plus `additional_data.pagination` with
`start`, `limit`, and `more_items_in_collection`. Pagination is resolved internally up
to `--limit`.

**Get/create/update commands** return `data` as a single object (the record).

**Delete/convert commands** return `data` with just the affected ID(s).

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "error": "...", "error_info": "..." },
  "message": "provider returned HTTP 404",
  "operation": "deals.get",
  "service": "pipedrive",
  "status": 404
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Pipedrive returned 4xx/5xx. Check `status` and `details.error` |
| `auth` | Authentication failed — missing or invalid API token |
| `config` | Missing or malformed config/secrets file |
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `network` | Could not reach the Pipedrive host |

Exit code is non-zero on any error.

# Pipedrive Leads Skill

Commands under `aai-cli pipedrive leads`.

---

## leads list

List leads. All filter flags are optional and AND-joined.

```
aai-cli pipedrive leads list [--limit N] [--owner-id ID] [--person-id ID] --profile pipedrive-work
                              [--organization-id ID] [--filter-id ID] [--updated-since TS]
                              [--sort SORT] [--archived]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max leads to return |
| `--owner-id` | no | Filter by owning user ID |
| `--person-id` | no | Filter by linked person ID |
| `--organization-id` | no | Filter by linked organization ID |
| `--filter-id` | no | Apply a saved Pipedrive filter |
| `--updated-since` | no | ISO timestamp — only leads updated at/after this time |
| `--sort` | no | Sort field/direction |
| `--archived` | no | Include archived leads |

## leads search

```
aai-cli pipedrive leads search --term TEXT [--fields LIST] [--exact-match] --profile pipedrive-work
                                [--person-id ID] [--organization-id ID] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--term` | **yes** | Search text |
| `--fields` | no | Comma-separated fields to search across |
| `--exact-match` | no | Require an exact match instead of partial |
| `--person-id` | no | Restrict results to a linked person |
| `--organization-id` | no | Restrict results to a linked organization |
| `--limit` | no | Max results to return |

## leads get

```
aai-cli pipedrive leads get <lead-id> --profile pipedrive-work
```

## leads create

```
aai-cli pipedrive leads create [--json <path|->] --title TEXT --profile pipedrive-work
                                [--person-id ID] [--organization-id ID] [--label-ids CSV]
```

| Flag | Required | Description |
|---|---|---|
| `--title` | **yes** (unless `--json` covers it) | Lead title |
| `--person-id` | no | Link to an existing person |
| `--organization-id` | no | Link to an existing organization |
| `--label-ids` | no | Comma-separated label IDs |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin). Flags override matching fields |

## leads update

```
aai-cli pipedrive leads update <lead-id> [--json <path|->] [--title TEXT] --profile pipedrive-work
                                [--person-id ID] [--organization-id ID] [--label-ids CSV]
```

Only the flags you pass are changed; omitted flags leave the field untouched.

## leads delete

```
aai-cli pipedrive leads delete <lead-id> --profile pipedrive-work
```

## leads convert

Converts a lead into a deal (and optionally a person/organization).

```
aai-cli pipedrive leads convert <lead-id> [--json <path|->] --profile pipedrive-work
```

# Pipedrive Persons Skill

Commands under `aai-cli pipedrive persons`.

---

## persons list

```
aai-cli pipedrive persons list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID] --profile pipedrive-work
                                [--org-id ID] [--deal-id ID] [--updated-since TS] [--updated-until TS]
                                [--sort-by FIELD] [--sort-direction asc|desc] [--include-labels]
```

## persons search

```
aai-cli pipedrive persons search --term TEXT [--fields LIST] [--exact-match] --profile pipedrive-work
                                  [--organization-id ID] [--limit N]
```

## persons get

```
aai-cli pipedrive persons get <person-id> [--include-labels] --profile pipedrive-work
```

## persons view

Combined JSON response containing the CRM record, activities, and notes.

```
aai-cli pipedrive persons view <person-id> [--limit N] [--include-labels] [--include-mail] --profile pipedrive-work
```

`--include-mail` adds associated email history — requires Pipedrive email synchronization
and permission to view those messages.

## persons activities / notes / mail-messages

```
aai-cli pipedrive persons activities <person-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive persons notes <person-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive persons mail-messages <person-id> [--limit N] --profile pipedrive-work
```

## persons create / update / delete

```
aai-cli pipedrive persons create [--json <path|->] --name TEXT [--org-id ID] --profile pipedrive-work
                                  [--email EMAIL] [--phone PHONE] [--label-ids CSV]
aai-cli pipedrive persons update <person-id> [--json <path|->] [--name TEXT] --profile pipedrive-work
                                  [--org-id ID] [--email EMAIL] [--phone PHONE] [--label-ids CSV]
aai-cli pipedrive persons delete <person-id> --profile pipedrive-work
```

# Pipedrive Organizations Skill

Commands under `aai-cli pipedrive organizations`.

---

## organizations list / search / get / view

```
aai-cli pipedrive organizations list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID] --profile pipedrive-work
                                      [--updated-since TS] [--updated-until TS]
                                      [--sort-by FIELD] [--sort-direction asc|desc] [--include-labels]
aai-cli pipedrive organizations search --term TEXT [--fields LIST] [--exact-match] [--limit N] --profile pipedrive-work
aai-cli pipedrive organizations get <organization-id> [--include-labels] --profile pipedrive-work
aai-cli pipedrive organizations view <organization-id> [--limit N] [--include-labels] [--include-mail] --profile pipedrive-work
```

## organizations activities / notes / mail-messages

```
aai-cli pipedrive organizations activities <organization-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive organizations notes <organization-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive organizations mail-messages <organization-id> [--limit N] --profile pipedrive-work
```

## organizations create / update / delete

```
aai-cli pipedrive organizations create [--json <path|->] --name TEXT [--address TEXT] [--label-ids CSV] --profile pipedrive-work
aai-cli pipedrive organizations update <organization-id> [--json <path|->] [--name TEXT] --profile pipedrive-work
                                        [--address TEXT] [--label-ids CSV]
aai-cli pipedrive organizations delete <organization-id> --profile pipedrive-work
```

# Pipedrive Deals Skill

Commands under `aai-cli pipedrive deals`. This is usually the most relevant resource for
sales workflows.

---

## deals list

```
aai-cli pipedrive deals list [--limit N] [--filter-id ID] [--ids CSV] [--owner-id ID] --profile pipedrive-work
                              [--person-id ID] [--org-id ID] [--pipeline-id ID] [--stage-id ID]
                              [--status open|won|lost|deleted] [--updated-since TS] [--updated-until TS]
                              [--sort-by FIELD] [--sort-direction asc|desc] [--include-labels]
```

## deals search

```
aai-cli pipedrive deals search --term TEXT [--fields LIST] [--exact-match] --profile pipedrive-work
                                [--person-id ID] [--organization-id ID] [--status open|won|lost] [--limit N]
```

## deals get / view

```
aai-cli pipedrive deals get <deal-id> [--include-labels] --profile pipedrive-work
aai-cli pipedrive deals view <deal-id> [--limit N] [--include-labels] [--include-mail] --profile pipedrive-work
```

`view` returns the combined CRM record + activities + notes; add `--include-mail` for
associated synced email history.

## deals activities / notes / mail-messages

```
aai-cli pipedrive deals activities <deal-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive deals notes <deal-id> [--limit N] --profile pipedrive-work
aai-cli pipedrive deals mail-messages <deal-id> [--limit N] --profile pipedrive-work
```

## deals create / update / delete

```
aai-cli pipedrive deals create [--json <path|->] --title TEXT [--person-id ID] [--org-id ID] --profile pipedrive-work
                                [--value NUM] [--currency CODE] [--pipeline-id ID] [--stage-id ID] [--label-ids CSV]
aai-cli pipedrive deals update <deal-id> [--json <path|->] [--title TEXT] --profile pipedrive-work
                                [--person-id ID] [--org-id ID] [--value NUM] [--currency CODE]
                                [--pipeline-id ID] [--stage-id ID] [--label-ids CSV]
aai-cli pipedrive deals delete <deal-id> --profile pipedrive-work
```

# Pipedrive Labels Skill

Commands under `aai-cli pipedrive labels`. Read-only for persons/deals/organizations
labels (they're managed in Pipedrive's own settings); leads labels support full CRUD.

```
aai-cli pipedrive labels leads list --profile pipedrive-work
aai-cli pipedrive labels leads create --name TEXT --color COLOR --profile pipedrive-work
aai-cli pipedrive labels leads update <label-id> [--name TEXT] [--color COLOR] --profile pipedrive-work
aai-cli pipedrive labels leads delete <label-id> --profile pipedrive-work
aai-cli pipedrive labels deals list --profile pipedrive-work
aai-cli pipedrive labels persons list --profile pipedrive-work
aai-cli pipedrive labels organizations list --profile pipedrive-work
```

# Pipedrive Activities, Notes, and Mailbox Skill

Commands under `aai-cli pipedrive activities`, `notes`, and `mailbox` — use these
directly when you need entries that aren't scoped to one lead/person/org/deal (the
per-resource `activities`/`notes`/`mail-messages` subcommands above are shortcuts scoped
to a single record).

---

## activities list / get

```
aai-cli pipedrive activities list [--deal-id ID] [--lead-id ID] [--person-id ID] [--org-id ID] --profile pipedrive-work
                                   [--owner-id ID] [--done true|false] [--updated-since TS] [--updated-until TS]
                                   [--sort-by FIELD] [--sort-direction asc|desc] [--include-attendees] [--limit N]
aai-cli pipedrive activities get <activity-id> --profile pipedrive-work
```

## notes list / get

```
aai-cli pipedrive notes list [--deal-id ID] [--lead-id ID] [--person-id ID] [--org-id ID] --profile pipedrive-work
                              [--user-id ID] [--sort SORT] [--start-date DATE] [--end-date DATE]
                              [--updated-since TS] [--limit N]
aai-cli pipedrive notes get <note-id> --profile pipedrive-work
```

## mailbox

Requires Pipedrive email synchronization to be enabled on the account and permission to
view the relevant messages.

```
aai-cli pipedrive mailbox messages get <message-id> [--include-body] --profile pipedrive-work
aai-cli pipedrive mailbox threads list [--folder inbox|drafts|sent|archive] [--limit N] --profile pipedrive-work
aai-cli pipedrive mailbox threads get <thread-id> --profile pipedrive-work
aai-cli pipedrive mailbox threads messages <thread-id> --profile pipedrive-work
```
""",
    },
]
