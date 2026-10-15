# aai-cli Merkys Skill

Agent reference for the `aai-cli merkys` command group.

## Global flags

Accepted by every command. Can also be set via environment variables.

| Flag | Env | Default | Description |
|---|---|---|---|
| `--profile NAME` | `AAI_PROFILE` | config `default_profile` | Profile from `~/.config/aai-cli/config.toml` |
| `--config PATH` | `AAI_CONFIG` | `~/.config/aai-cli/config.toml` | Path to config file |
| `--secrets-file PATH` | `AAI_SECRETS_FILE` | `~/.config/aai-cli/secrets.enc.json` | Path to encrypted secrets file |
| `--key-file PATH` | `AAI_SECRET_KEY_FILE` | `/run/aai/key` or `~/.config/aai-cli/key` | Path to decryption key file |

## Profile

```toml
[profiles.merkys-work]
provider = "merkys"
auth_type = "api_key_header"
base_url = "https://merkys.example.com"
api_token_secret = "merkys.api_key"
```

The key is a Merkys **user API key** and is sent as `X-API-Key` (override the header name with `api_key_header` only if a deployment uses a different one). There is no default `base_url`: each Merkys deployment has its own. Service credentials (bearer) are a different credential type and do not work here.

## Commands

### ask

```
aai-cli merkys ask <question> [--conversation-id ID]
```

Creates a conversation (unless `--conversation-id` is given), sends the question, then reads the stored answer back for its sources. Not paginated. Output:

```json
{
  "conversation_id": "6ad082d7e4047fa93a60fef6",
  "message_id": "6ad082dbe4047fa93a60fef9",
  "answer": "WebGLM is an efficient web-enhanced question-answering system ... [[1]]",
  "sources": [
    {
      "index": 1,
      "type": "document",
      "title": "webglm.pdf",
      "page_number": 8,
      "excerpt": "Firstly, we compare each pair of the answers, the win rate is shown in Figure 6 ...",
      "resource_id": "6ad07866e4047fa93a60fe57",
      "link": "",
      "data_source_id": ""
    }
  ],
  "detect_conflicts": { "has_conflict": false, "conflicts": [] },
  "faithfulness": null,
  "total_tokens": 4684
}
```

`sources` is `[]` when the answer used no sources and `null` (with a `warning`) when the lookup failed. `detect_conflicts` is non-null when sources disagree. `link` is a URL for connected sources (Jira, Confluence, web) and empty for uploads. Each ask creates a conversation unless one is passed.

### research start

```
aai-cli merkys research start <question> [--conversation-id ID] [--wait] [--timeout-secs N] [--poll-secs N]
```

Starts a deep research run (plan, several searches, written report). Without `--wait`:

```json
{ "run_id": "a8052bd7-cbd7-4929-a5b8-18c51045fa14", "conversation_id": "6ad0824de4047fa93a60fed2" }
```

With `--wait` it polls until `status` is `completed` or `failed` and returns the run:

```json
{
  "run_id": "a8052bd7-...",
  "conversation_id": "6ad0824d...",
  "status": "completed",
  "question": "Summarize the WebGLM paper: its three components and main results.",
  "plan": ["What are the three components of the WebGLM paper?", "..."],
  "sub_queries": [{ "status": "completed", "findings": "...", "error": null }],
  "final_report": "# Research Report: Summary of the WebGLM paper\n\n...",
  "sources": [{ "index": 1, "title": "webglm.pdf", "page_number": 8, "excerpt": "..." }],
  "total_tokens": 22463,
  "error_reason": null,
  "failing_step": null
}
```

A real run of this size took about 75 seconds. `status` is one of `pending`, `running`, `completed`, `failed`. When `--wait` times out the error has `code: "timeout"` and `details.run_id`; the run keeps going.

### research get / research stop

```
aai-cli merkys research get <run-id>
aai-cli merkys research stop <run-id>
```

`get` returns the run shape above at any point. `stop` asks a running run to stop.

### conversations list

```
aai-cli merkys conversations list [--limit N] [--page-token TOKEN]
```

The key owner's conversations, newest first. Response: `items[]` (`id`, `title`, `created_at`, `updated_at`, `status`), `page_size`, `next_page_token`, `previous_page_token`. Pagination follows `next_page_token`; pass it back with `--page-token`.

### conversations search

```
aai-cli merkys conversations search <query> [--limit N] [--page-token TOKEN]
```

Same shape as `list`, with `score`, `match_source` (`title` or message), and `snippet` on each item.

### conversations messages

```
aai-cli merkys conversations messages <conversation-id> [--limit N] [--page-token TOKEN]
```

Messages oldest to newest. Assistant messages carry `text`, `sources[]`, `tool_calls[]`, `faithfulness`, `total_tokens`. Paginated with `next_page_token`.

### documents list

```
aai-cli merkys documents list [--limit N]
```

Uploaded documents. Returns a bare list, wrapped by this CLI as `results[]` (`id`, `filename`, `file_size`, `mime_type`, `status`, `chunk_count`, `acl_public`, `acl_emails`, `acl_role_tags`, `ingestion_error_message`). `status: "completed"` means the document is searchable.

### sources list

```
aai-cli merkys sources list [--limit N] [--offset N]
```

Connected data sources (Jira, Confluence, Drive, email, web, ...). Empty for a key owner who cannot see any.

### assistants list

```
aai-cli merkys assistants list
```

Custom assistants the key owner can use. Empty when none are configured.

### request

```
aai-cli merkys request get <relative-path> [--query key=value ...]
aai-cli merkys request post <relative-path> --allow-write [--json <path|->] [--query key=value ...]
```

Escape hatch for any endpoint, with profile authentication. GET and HEAD need nothing extra. Other methods require `--allow-write`; do not use them for knowledge lookups. `PATH` is relative to `base_url`. Example:

```
aai-cli merkys request get /api/limits
```

The condensed endpoint list is in [api-endpoints.md](api-endpoints.md).

## Pagination

Successful output carries the usual `_aai.pagination` block. For `conversations` commands, `status: "more_available"` with a `continuation` of `page_token` means pass that token back to continue. `documents list` and `sources list` do not report a next page: if `returned_count` equals `--limit`, raise the limit.
