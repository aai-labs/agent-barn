# aai-cli Zoho Mail Skill

Agent reference for the `aai-cli email` command group with a Zoho Mail profile.

## Required flag

Every command requires `--profile zoho-mail-rest`. Always include it.

```
aai-cli email <command> --profile zoho-mail-rest [other flags]
```

## Response shapes

**`messages list`** returns rich message objects with `messageId`, `subject`, `fromAddress`, `receivedTime`, `summary`, and `folderId` inline — no secondary `get` needed to identify an email.

**`messages get`** returns a human-readable object: `id`, `subject`, `from`, `to`, `date`, `body` (decoded plain text), `body_type` (`"text"` or `"html"`).

Date filtering on `messages list` is client-side: up to 200 messages are fetched then filtered by `receivedTime`. `truncated: true` in the response means more matches exist beyond the fetched page.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "status": "error", "message": "..." },
  "message": "provider returned HTTP 401",
  "operation": "messages.list",
  "service": "email",
  "status": 401
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Zoho returned 4xx/5xx. Check `status` and `details.message` |
| `auth` | Missing or invalid token |
| `invalid_input` | A required flag was missing or rejected |
| `network` | Could not reach Zoho Mail |

Exit code is non-zero on any error.

---

## messages list

List messages in the inbox.

```
aai-cli email messages list [--limit N] [--received-after DATE] [--received-before DATE] --profile zoho-mail-rest
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max messages to return. Default: `50` |
| `--received-after` | no | ISO date lower bound (inclusive), e.g. `2026-06-01`. Filtered client-side on `receivedTime` |
| `--received-before` | no | ISO date upper bound (exclusive), e.g. `2026-06-19`. Filtered client-side on `receivedTime` |

**Example**

```
aai-cli email messages list --limit 3 --profile zoho-mail-rest
```

```json
{
  "data": [
    {
      "folderId": "56218000000008014",
      "fromAddress": "confluence@aai-labs.atlassian.net",
      "hasAttachment": "0",
      "messageId": "1781850728498141700",
      "receivedTime": "1781850728475",
      "subject": "Samuel Birhanu, don't miss out on your daily digest",
      "summary": "G'day Samuel Birhanu, Hope you're having a great day...",
      "toAddress": "\"Samuel Birhanu\"<samuel@aai-labs.com>"
    }
  ],
  "status": { "code": 200, "description": "success" }
}
```

**Example — date range**

```
aai-cli email messages list --limit 5 --received-after 2026-06-01 --received-before 2026-06-19 --profile zoho-mail-rest
```

```json
{
  "data": [
    {
      "fromAddress": "noreply@async.doasync.com",
      "messageId": "1781696261967141700",
      "receivedTime": "1781696261958",
      "subject": "Game invitation: Sprint 7"
    },
    {
      "fromAddress": "no-reply@email.slackhq.com",
      "messageId": "1781687630086141700",
      "receivedTime": "1781687630064",
      "subject": "Don't miss our Admin Roadmap Preview webinar"
    }
  ],
  "status": { "code": 200, "description": "success" },
  "truncated": true
}
```

Use `messageId` as `<MESSAGE_ID>` in `messages get`.

---

## messages get

Fetch a single message by ID. Returns decoded subject and body.

```
aai-cli email messages get <MESSAGE_ID> --profile zoho-mail-rest
```

| Argument | Required | Description |
|---|---|---|
| `MESSAGE_ID` | **yes** | Zoho message ID (from `messages list`) |

**Example**

```
aai-cli email messages get 1781850728498141700 --profile zoho-mail-rest
```

```json
{
  "id": "1781850728498141700",
  "subject": "Samuel Birhanu, don't miss out on your daily digest: Armantas Ostapenka has made updates on \"Common blueprint error investigation\"",
  "from": "Confluence <confluence@aai-labs.atlassian.net>",
  "to": "Samuel Birhanu <samuel@aai-labs.com>",
  "date": "Fri, 19 Jun 2026 06:32:07 +0000",
  "body": "G'day Samuel Birhanu,\nHope you're having a great day. There has been 1 update since Thursday, June 18, 2026.\n\nCommon blueprint error investigation\nArmantas Ostapenka made updates...",
  "body_type": "text"
}
```

`body_type` is `"text"` when a `text/plain` MIME part was found, `"html"` when only HTML was available (tags stripped).

