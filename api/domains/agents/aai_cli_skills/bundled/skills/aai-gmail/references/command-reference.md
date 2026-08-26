# aai-cli Gmail Skill

Agent reference for the `aai-cli email` command group with a Gmail profile.

## Required flag

Every command requires `--profile gmail-work`. Always include it.

```
aai-cli email <command> --profile gmail-work [other flags]
```

## Response shapes

**`messages list`** returns message stubs (`id` + `threadId` only). Use `messages get <id>` to fetch subject and body.

**`messages get`** returns a human-readable object: `id`, `thread_id`, `subject`, `from`, `to`, `date`, `body` (decoded plain text), `body_type` (`"text"`, `"html"`, or `"snippet"`).

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "error": { "code": 401, "message": "..." } },
  "message": "provider returned HTTP 401",
  "operation": "messages.list",
  "service": "email",
  "status": 401
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Gmail returned 4xx/5xx. Check `status` and `details.error.message` |
| `auth` | Missing or invalid token |
| `invalid_input` | A required flag was missing or rejected |
| `network` | Could not reach Gmail |

Exit code is non-zero on any error.

---

## messages list

List messages in the inbox. Returns stubs — use `messages get` to read content.

```
aai-cli email messages list [--limit N] [--received-after DATE] [--received-before DATE] --profile gmail-work
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max messages to return. Default: `50` |
| `--received-after` | no | ISO date lower bound (inclusive), e.g. `2026-06-01`. Passed to Gmail as `after:YYYY/MM/DD` |
| `--received-before` | no | ISO date upper bound (exclusive), e.g. `2026-06-19`. Passed to Gmail as `before:YYYY/MM/DD` |

**Example**

```
aai-cli email messages list --limit 3 --profile gmail-work
```

```json
{
  "messages": [
    { "id": "19ede287c1ca8ad4", "threadId": "19ede287c1ca8ad4" },
    { "id": "19edd2db3db0c61b", "threadId": "19edd2db3db0c61b" },
    { "id": "19edc98fb3ce68e8", "threadId": "19edc98fb3ce68e8" }
  ],
  "nextPageToken": "08354791619698930432",
  "resultSizeEstimate": 201
}
```

**Example — date range**

```
aai-cli email messages list --limit 5 --received-after 2026-06-01 --received-before 2026-06-19 --profile gmail-work
```

```json
{
  "messages": [
    { "id": "19edc98fb3ce68e8", "threadId": "19edc98fb3ce68e8" },
    { "id": "19edc7496a0689e3", "threadId": "19edc7496a0689e3" }
  ],
  "nextPageToken": "04900535494567325000",
  "resultSizeEstimate": 201
}
```

---

## messages get

Fetch a single message by ID. Returns decoded subject and body.

```
aai-cli email messages get <MESSAGE_ID> --profile gmail-work
```

| Argument | Required | Description |
|---|---|---|
| `MESSAGE_ID` | **yes** | Gmail message ID (from `messages list`) |

**Example**

```
aai-cli email messages get 19ede287c1ca8ad4 --profile gmail-work
```

```json
{
  "id": "19ede287c1ca8ad4",
  "thread_id": "19ede287c1ca8ad4",
  "subject": "Everything we released at WWDC, Google I/O, and Cloud Next '26",
  "from": "Google Developer Program <googledev-noreply@google.com>",
  "to": "samibre121@gmail.com",
  "date": "Thu, 18 Jun 2026 21:34:15 -0700",
  "body": "Bringing the latest Gemini models to Apple developers\n\nAt the Worldwide Developers Conference (WWDC), Apple announced that it's opening its Foundation Models framework to third-party cloud model providers...",
  "body_type": "text"
}
```

`body_type` is `"text"` when a `text/plain` MIME part was found, `"html"` when only HTML was available (tags stripped), or `"snippet"` when no body could be decoded.

