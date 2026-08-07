"""aai-cli slack skill docs."""

SLACK_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/slack_skill.md",
        "skill_content": """\
# aai-cli Slack Skill

Agent reference for the `aai-cli slack` command group.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, bot
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flag

Every command requires `--profile slack-work`. Always include it.

```
aai-cli slack <command> --profile slack-work [other flags]
```

## Read-only integration

This is a **read-only** integration — there is no message-sending and no OAuth install
flow, only channel data reads (channels, files, bookmarks, links, canvas). The bot must
be a **member of a channel** to read its files, bookmarks, and message history — the
channel must have the bot invited (`/invite @your-bot-name`) before any of these commands
return data for it, even with the correct scopes granted at the app level.

## Response shapes

Successful command output is JSON on stdout, always wrapped with an `_aai`
pagination-metadata block from this CLI (not part of the raw Slack response):

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
  "...": "rest of the provider response"
}
```

**`channels get`** returns Slack's `conversations.info` response verbatim, plus one added
field: `channel.canvas_id` (a string, or `null` if the channel has no canvas). This field
does not exist in Slack's raw API — it's extracted from `channel.properties.tabs[]` where
`type == "canvas"`. It is **not** at `properties.canvas` despite that being a reasonable
guess.

**List commands** (`channels list`, `files list`, `links list`) aggregate provider pages
up to `--limit` and return the raw provider list shape (`channels`/`files`/`links` array
plus provider metadata), with an added top-level `has_more` boolean this CLI sets
explicitly so pagination status is accurate even when Slack's own response has no
continuation marker to check.

**`bookmarks list`** has no `--limit` — Slack returns all (at most 100) bookmarks for a
channel in one call, so this command is never paginated.

**`links list`** does not return a raw Slack shape at all — it's a derived view built by
extracting links from `conversations.history` message blocks (walking each message's
`blocks[].elements[].elements[]` for `type == "link"`, reading `.url`). This intentionally
does **not** scan `message.text` — Slack truncates display text there and HTML-escapes it
(e.g. renders `&` as `&amp;`), which silently mangles or drops URLs. Response is
`{ "links": [{url, text, message_ts}, ...], "has_more": bool }`. There is no
`message_permalink` field — use `message_ts` with `slack request` (`chat.getPermalink`) if
a permalink is needed for a specific message.

**`files download`** and **`canvas download`** return JSON metadata only, never file
content to stdout: `{ "output": "<path>", "bytes": N, "file_id"|"canvas_id": "<id>",
"title": "<title>" }`. The downloaded file itself is written to `--output` — an HTML
fragment for canvases (Slack's internal canvas format, not markdown), native bytes for
everything else.

## Error response shape

All errors print to stderr as a single JSON line. Slack signals most API-level errors as
HTTP 200 with `{"ok": false, "error": "<code>"}` rather than a non-2xx status — this CLI
inspects the body and maps Slack's `error` string onto the same error taxonomy every other
service uses:

```json
{"code":"not_found","details":{"error":"channel_not_found","ok":false},"message":"slack returned error 'channel_not_found'","operation":"channels.get","service":"slack","status":404}
```

| Code | Meaning | Example Slack `error` values |
|---|---|---|
| `invalid_input` | A required flag was missing or a value was rejected before the API call | — |
| `config_error` | Missing or malformed config, profile, or token setting | — |
| `auth_error` | Missing credentials, invalid token, missing scope, or provider 401/403 | `invalid_auth`, `not_authed`, `token_revoked`, `token_expired`, `account_inactive`, `missing_scope` |
| `not_found` | Provider indicates the resource doesn't exist or isn't visible to this bot | `channel_not_found`, `not_visible`, `file_not_found`, `thread_not_found` |
| `rate_limited` | Real HTTP 429, or Slack's `ratelimited` error code | `ratelimited` |
| `provider_api_error` | Any other Slack `ok:false` error, or another 4xx/5xx | anything else |
| `internal_error` | Local request, response, or IO failure | — |

Exit code is non-zero on any error.

# Slack Channels Skill

Commands under `aai-cli slack channels`.

---

## channels list

```
aai-cli slack channels list [--limit N] [--types public_channel,private_channel] --profile slack-work
```

`--types` is passed straight through to Slack's `conversations.list` as a comma-separated
list (`public_channel`, `private_channel`, `mpim`, `im`).

**Example**

```
aai-cli --profile slack-work slack channels list --limit 5
```

```json
{
  "channels": [
    {
      "context_team_id": "T0B52TY7F1S",
      "created": 1779257848,
      "creator": "U0B4ZA25F5Y",
      "id": "C0B4HS4J6J3",
      "is_archived": false,
      "is_channel": true,
      "is_general": true,
      "is_member": false,
      "is_private": false,
      "name": "all-agent-farm-test-workspace",
      "num_members": 2,
      "purpose": { "value": "Share announcements and updates...", "creator": "U0B4ZA25F5Y", "last_set": 1779257848 },
      "topic": { "value": "", "creator": "", "last_set": 0 }
    }
  ],
  "has_more": true
}
```

When more channels are available than `--limit`, `_aai.pagination.continuation.parameters`
carries the cursor Slack returned (`response_metadata.next_cursor`), and `next_command`
suggests rerunning with a larger `--limit`.

---

## channels get

```
aai-cli slack channels get <channel-id> --profile slack-work
```

**Example**

```
aai-cli --profile slack-work slack channels get C0BLNH0K26B
```

```json
{
  "channel": {
    "canvas_id": "F0BM3V2MP9Q",
    "id": "C0BLNH0K26B",
    "name": "aai-cli-lack-test",
    "is_channel": true,
    "is_private": false,
    "is_archived": false,
    "is_member": true,
    "properties": {
      "meeting_notes": { "file_id": "F0BM3V2MP9Q" },
      "tabs": [
        { "id": "files", "label": "", "type": "files" },
        {
          "id": "Ct0BM0KTM84V",
          "type": "canvas",
          "data": { "file_id": "F0BM3V2MP9Q", "shared_ts": "1785483700.717999" },
          "label": ""
        },
        {
          "id": "Ct0BM0L4971B",
          "label": "Bookmarks",
          "type": "folder",
          "data": { "folder_bookmark_id": "Bk0BM20FGFQE" }
        }
      ]
    },
    "purpose": { "value": "", "creator": "", "last_set": 0 },
    "topic": { "value": "", "creator": "", "last_set": 0 }
  },
  "ok": true
}
```

**Note:** `canvas_id` is extracted from `properties.tabs[]` where `type == "canvas"` — it
is **not** a native Slack field, and it is **not** at `properties.canvas` despite that
being a reasonable guess. If a channel has no canvas tab, `canvas_id` is `null`.

# Slack Files Skill

Commands under `aai-cli slack files`.

---

## files list

```
aai-cli slack files list <channel-id> [--limit N] --profile slack-work
```

Wraps Slack's `files.list?channel=`, page/count-paginated (not cursor-based, unlike most
other list commands in this CLI). Canvas files appear in this list too, distinguishable by
`filetype: "quip"` / `pretty_type: "Canvas"` — no filtering is applied.

**Example** (truncated — real response includes more file metadata fields)

```
aai-cli --profile slack-work slack files list C0BLNH0K26B
```

```json
{
  "files": [
    {
      "id": "F0BM1V4U1HU",
      "name": "webglm.pdf",
      "title": "webglm.pdf",
      "filetype": "pdf",
      "pretty_type": "PDF",
      "mimetype": "application/pdf",
      "size": 5263143,
      "user": "U0B4ZA25F5Y",
      "url_private": "https://files.slack.com/files-pri/T0B52TY7F1S-F0BM1V4U1HU/webglm.pdf",
      "url_private_download": "https://files.slack.com/files-pri/T0B52TY7F1S-F0BM1V4U1HU/download/webglm.pdf",
      "channels": ["C0BLNH0K26B"]
    },
    {
      "id": "F0BM3V2MP9Q",
      "name": "Sample_canvas_title",
      "title": "Sample canvas title",
      "filetype": "quip",
      "pretty_type": "Canvas",
      "mimetype": "application/vnd.slack-docs",
      "size": 453,
      "channels": ["C0BLNH0K26B"]
    }
  ],
  "has_more": false,
  "paging": { "count": 50, "page": 1, "pages": 1, "total": 2 }
}
```

---

## files download

```
aai-cli slack files download <file-id> --output PATH --profile slack-work
```

Takes a file `id` from `files list`, resolves its `url_private_download` via `files.info`,
and writes the raw bytes to `--output`. Returns JSON metadata only, never file content to
stdout: `{ "output": "<path>", "bytes": N, "file_id": "<id>", "title": "<file title>" }`.
Shares the exact same download mechanism as `canvas download` (below) — the only
difference between the two commands is how each resolves which file ID to download.

> Pending a live-captured example (bot token was rotated after the last verification
> pass) — response shape confirmed by code review against the identical,
> already-live-verified `canvas download` path.

# Slack Bookmarks Skill

Commands under `aai-cli slack bookmarks`.

---

## bookmarks list

```
aai-cli slack bookmarks list <channel-id> --profile slack-work
```

No `--limit` — Slack caps channels at 100 bookmarks and this always returns them all in
one call.

**Example**

```
aai-cli --profile slack-work slack bookmarks list C0BLNH0K26B
```

```json
{
  "bookmarks": [
    {
      "id": "Bk0BMY9WA1TJ",
      "channel_id": "C0BLNH0K26B",
      "title": "Log in with Atlassian account",
      "link": "https://aai-labs.atlassian.net",
      "type": "link",
      "date_created": 1785483802
    },
    {
      "id": "Bk0BM4026EAE",
      "channel_id": "C0BLNH0K26B",
      "title": "AAI Labs",
      "link": "http://aai-labs.com",
      "type": "link",
      "date_created": 1785483824
    }
  ],
  "has_more": false
}
```

# Slack Links Skill

Commands under `aai-cli slack links`.

---

## links list

```
aai-cli slack links list <channel-id> [--limit N] --profile slack-work
```

Extracts links from `conversations.history` by walking each message's
`blocks[].elements[].elements[]` for `type == "link"`, reading `.url`. This intentionally
does **not** scan `message.text` — Slack truncates display text there and HTML-escapes it
(e.g. renders `&` as `&amp;`), which silently mangles or drops URLs.

**Example** (real message, showing the extraction is correct where the raw `message.text`
would have been wrong)

```
aai-cli --profile slack-work slack links list C0BLNH0K26B
```

```json
{
  "links": [
    {
      "url": "https://aai-labs.atlassian.net/jira/software/projects/AF/boards/1052?filter=&groupBy=none",
      "text": "aai-labs.atlassian.net/jira/…/1052?groupBy=none&…",
      "message_ts": "1785483401.603779"
    }
  ],
  "has_more": false
}
```

The raw message's `text` field for this same message was
`"...&amp;groupBy=none|aai-labs.atlassian.net/jira/…/1052?groupBy=none&…"` — truncated and
HTML-escaped. The `url` field above is the real, complete, correctly-decoded link.

There is no `message_permalink` field. Building one correctly needs either an extra
`chat.getPermalink` call per link or a hand-rolled URL that's wrong in thread/Enterprise-Grid
edge cases — use `message_ts` with `slack request` (`chat.getPermalink`) if a permalink is
needed for a specific message.

# Slack Canvas Skill

Commands under `aai-cli slack canvas`.

---

## canvas download

```
aai-cli slack canvas download <channel-id> --output PATH --profile slack-work
```

Resolves the channel's canvas (same lookup `channels get` uses for `canvas_id`), downloads
it via Slack's `url_private_download` with the bot token, and writes it to `--output`. A
channel with no canvas tab returns `not_found`.

**Example**

```
aai-cli --profile slack-work slack canvas download C0BLNH0K26B --output /tmp/canvas.html
```

```json
{
  "bytes": 598,
  "canvas_id": "F0BM3V2MP9Q",
  "output": "/tmp/canvas.html",
  "title": "Sample canvas title"
}
```

Contents of `/tmp/canvas.html` (real captured canvas content — an HTML fragment, not
markdown, despite Slack's own docs describing canvas content as markdown on the write
side):

```html
<div class="quip-canvas-content"><h1 id="temp:C:dOQ250184c27aed403bb6962b95d">Sample canvas title</h1><p id="temp:C:dOQ4460142af50840c2bd174c6df" class="line">sample canvas body. this should be one paragraph. ...</p></div>
```

Ordinary (non-canvas) files use the exact same download mechanism, but return their native
bytes/content-type instead of this HTML fragment — there is no special-casing, only the
*lookup* of which file to download differs between the two.

# Slack Request Skill

Commands under `aai-cli slack request`.

---

## request

```
aai-cli slack request get <relative-path> [--query key=value ...] --profile slack-work
aai-cli slack request post <relative-path> --allow-write [--json <path|->] [--query key=value ...] --profile slack-work
```

Escape hatch for Slack Web API methods this CLI doesn't wrap with a typed command (for
example `chat.getPermalink`, or any write endpoint — this CLI's typed Slack commands are
all read-only). Same rules as every other service's `request` command: relative paths
only, GET/HEAD reject `--json`, writes require `--allow-write`.

**Example** (cursor-paginated generic call — the pagination pointer for Slack's
`response_metadata.next_cursor` is recognized, so `next_command` splices the cursor into
the next invocation)

```
aai-cli --profile slack-work slack request get conversations.list --query limit=1
```

```json
{
  "_aai": {
    "pagination": {
      "continuation": {
        "next_url": null,
        "parameters": [{ "key": "cursor", "value": "dGVhbTpDMEI0VzU3SlZFWg==" }],
        "source": "response_metadata.next_cursor"
      },
      "has_more": true,
      "next_command": "aai-cli --profile slack-work slack request get conversations.list --query limit=1 --query cursor=dGVhbTpDMEI0VzU3SlZFWg==",
      "returned_count": 1,
      "status": "more_available"
    }
  },
  "channels": [{ "id": "C0B4HS4J6J3", "name": "all-agent-farm-test-workspace" }],
  "ok": true,
  "response_metadata": { "next_cursor": "dGVhbTpDMEI0VzU3SlZFWg==" }
}
```
""",
    },
]
