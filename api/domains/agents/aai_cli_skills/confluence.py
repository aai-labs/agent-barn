"""aai-cli confluence skill docs."""

CONFLUENCE_SKILLS: list[dict[str, str]] = [
    {
        "skill_file_path": "aai-cli/confluence_skill.md",
        "skill_content": """\
# aai-cli Confluence Skill

Agent reference for the `aai-cli confluence` command group.

## IMPORTANT: credentials are already configured

The tool is fully set up on this agent. **Do not ask the user for credentials, site URLs,
tokens, or any config details.** The profile is on disk and ready. Just run the command.

If the command returns an error, show the raw error output to the user — do not ask them
to provide config or credentials.

## Required flag

Every command requires `--profile confluence-work`. Always include it.

```
aai-cli confluence <command> --profile confluence-work [other flags]
```
## Response shapes

**List commands** return trimmed responses: UI-only fields (`_links`, `_expandable`, avatar URLs, `self`) are stripped. Pagination is resolved internally up to `--limit`. The envelope always includes `limit`, `size`, and `results`.

**Get commands** return the full raw API response.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "errorMessages": ["..."], "errors": {} },
  "message": "provider returned HTTP 400",
  "operation": "pages.update",
  "service": "confluence",
  "status": 400
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Confluence returned 4xx/5xx. Check `status` and `details.errorMessages` |
| `auth` | Authentication failed — missing or invalid token |
| `config` | Missing or malformed config/secrets file |
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `network` | Could not reach the Confluence host |

Exit code is non-zero on any error.

# Confluence Page Attachments Skill

Commands under `aai-cli confluence pages attachments`.

---

## pages attachments list

List attachments on a page. Returns trimmed attachment objects (UI links and verbose metadata stripped).

```
aai-cli confluence pages attachments list <PAGE_ID> [--limit N] --profile confluence-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |
| `--limit` | no | Max attachments to return. Default: `25` |

**Example**

```
aai-cli confluence pages attachments list 3964929 --limit 5 --profile confluence-work
```

```json
{
  "limit": 5,
  "results": [
    {
      "comment": "Uploaded for skill doc test",
      "createdAt": "2026-05-27T07:15:20.913Z",
      "downloadLink": "/download/attachments/3964929/skill_doc_test.txt?version=1&modificationDate=1779866120913&cacheVersion=1&api=v2",
      "fileSize": 30,
      "id": "att3997705",
      "mediaType": "text/plain",
      "title": "skill_doc_test.txt",
      "version": {
        "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
        "createdAt": "2026-05-27T07:15:20.913Z",
        "number": 1
      }
    }
  ],
  "size": 1
}
```

Use `id` from this response as `<ATTACHMENT_ID>` in the download command.

---

## pages attachments download

Download an attachment's binary content to a local file. Requires both the page ID and attachment ID.

```
aai-cli confluence pages attachments download <PAGE_ID> <ATTACHMENT_ID> --output <PATH> --profile confluence-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID (the page the attachment belongs to) |
| `ATTACHMENT_ID` | **yes** | Attachment ID from `attachments list` (e.g. `att3997705`) |
| `--output` | **yes** | Local file path to write the downloaded content |

**Example**

```
aai-cli confluence pages attachments download 3964929 att3997705 --output /tmp/skill_doc_downloaded.txt --profile confluence-work
```

```json
{
  "bytes": 30,
  "output": "/tmp/skill_doc_downloaded.txt"
}
```

---

## pages attachments upload

Upload a local file as an attachment to a page. If an attachment with the same filename already exists on the page, a new version of that attachment is created.

```
aai-cli confluence pages attachments upload <PAGE_ID> --file <PATH> [--comment TEXT] --profile confluence-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |
| `--file` | **yes** | Local file path to upload |
| `--comment` | no | Version comment for the attachment |

Returns the created attachment object (first element of the Confluence v1 `results` array).

**Example**

```
aai-cli confluence pages attachments upload 3964929 --file /tmp/skill_doc_test.txt --comment "Uploaded for skill doc test" --profile confluence-work
```

```json
{
  "extensions": {
    "collectionName": "contentId-3964929",
    "comment": "Uploaded for skill doc test",
    "fileId": "d5d32e4c-dc3f-44ae-b57c-5098648aebde",
    "fileSize": 30,
    "mediaType": "text/plain",
    "mediaTypeDescription": "Text File"
  },
  "id": "att3997705",
  "status": "current",
  "title": "skill_doc_test.txt",
  "type": "attachment",
  "version": {
    "by": {
      "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
      "displayName": "Marselle Wing",
      "email": "marsellewing@gmail.com"
    },
    "contentTypeModified": false,
    "message": "Uploaded for skill doc test",
    "number": 1,
    "when": "2026-05-27T07:15:20.913Z"
  }
}
```

# Confluence Page Comments Skill

Commands under `aai-cli confluence pages comments`.

---

## pages comments list

List comments on a page. Returns `page_comments` (top-level and threaded replies) and `inline_comments`. Avatar URLs and UI-only links are stripped.

```
aai-cli confluence pages comments list <PAGE_ID> [--limit N] --profile confluence-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |
| `--limit` | no | Max comments to return. Default: `25` |

**Example**

```
aai-cli confluence pages comments list 3964929 --limit 10 --profile confluence-work
```

```json
{
  "inline_comments": [],
  "page_comments": [
    {
      "body": {
        "storage": {
          "representation": "storage",
          "value": "This is a skill doc test comment."
        }
      },
      "id": "4063233",
      "replies": [
        {
          "body": {
            "storage": {
              "representation": "storage",
              "value": "This is a reply comment."
            }
          },
          "id": "3964950",
          "parentCommentId": "4063233",
          "replies": [],
          "status": "current",
          "title": "Re: aai-cli skill doc test page (updated)",
          "version": {
            "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
            "createdAt": "2026-05-27T07:17:58.189Z",
            "number": 1
          }
        }
      ],
      "resolutionStatus": "open",
      "status": "current",
      "title": "Re: aai-cli skill doc test page (updated)",
      "version": {
        "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
        "createdAt": "2026-05-27T07:15:13.896Z",
        "number": 1
      }
    }
  ]
}
```

---

## pages comments create

Add a comment to a page. Use `--body` for plain text (stored as Confluence storage format), or `--json` for a pre-built body. Use `--reply-to` to create a nested reply to an existing comment.

```
aai-cli confluence pages comments create <PAGE_ID> [--body TEXT] [--reply-to COMMENT_ID] --profile confluence-work
                                         [--json JSON_OR_PATH]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |
| `--body` | **yes** (unless `--json` covers it) | Comment body text |
| `--reply-to` | no | Numeric comment ID to reply to (creates a nested reply) |
| `--json` | no | Raw Confluence comment body JSON. Flags override matching fields |

**Example — top-level comment**

```
aai-cli confluence pages comments create 3964929 --body "This is a skill doc test comment." --profile confluence-work
```

```json
{
  "_links": {
    "base": "https://marsellewing.atlassian.net/wiki",
    "webui": "/spaces/SD/pages/3964929/aai-cli+skill+doc+test+page+updated?focusedCommentId=4063233"
  },
  "body": {
    "storage": {
      "representation": "storage",
      "value": "This is a skill doc test comment."
    }
  },
  "id": "4063233",
  "pageId": "3964929",
  "status": "current",
  "title": "Re: aai-cli skill doc test page (updated)",
  "version": {
    "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "createdAt": "2026-05-27T07:15:13.896Z",
    "number": 1
  }
}
```

**Example — reply to an existing comment**

```
aai-cli confluence pages comments create 3964929 --body "This is a reply comment." --reply-to 4063233 --profile confluence-work
```

```json
{
  "_links": {
    "base": "https://marsellewing.atlassian.net/wiki",
    "webui": "/spaces/SD/pages/3964929/aai-cli+skill+doc+test+page+updated?focusedCommentId=3964950"
  },
  "body": {
    "storage": {
      "representation": "storage",
      "value": "This is a reply comment."
    }
  },
  "id": "3964950",
  "pageId": "3964929",
  "parentCommentId": "4063233",
  "status": "current",
  "title": "Re: aai-cli skill doc test page (updated)",
  "version": {
    "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "createdAt": "2026-05-27T07:17:58.189Z",
    "number": 1
  }
}
```

# Confluence Pages Skill

Commands under `aai-cli confluence pages`.

---

## pages list

List pages with optional filters. All filter flags are optional and AND-joined.

```
aai-cli confluence pages list [--space KEY_OR_ID] [--title TEXT] [--status STATUS] --profile confluence-work
                              [--parent-id ID] [--limit N]
```

| Flag | Required | Type | Description |
|---|---|---|---|
| `--space` | no | string | Space key (e.g. `SD`) or numeric space ID |
| `--title` | no | string | Filter by exact title match |
| `--status` | no | string | Page status: `current`, `archived`, `trashed`. Default: `current` |
| `--parent-id` | no | string | Return only direct children of this page ID |
| `--limit` | no | integer | Max pages to return. Default: `50` |

**Example — space + status + limit**

```
aai-cli confluence pages list --space SD --status current --limit 3 --profile confluence-work
```

```json
{
  "limit": 3,
  "results": [
    {
      "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
      "createdAt": "2026-05-13T14:55:23.386Z",
      "id": "98422",
      "parentId": null,
      "parentType": null,
      "spaceId": "98309",
      "status": "current",
      "title": "Software Development",
      "version": {
        "createdAt": "2026-05-13T14:55:28.624Z",
        "number": 1
      }
    },
    {
      "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
      "createdAt": "2026-05-13T14:55:28.341Z",
      "id": "98462",
      "parentId": "98422",
      "parentType": "page",
      "spaceId": "98309",
      "status": "current",
      "title": "Template - Product requirements",
      "version": {
        "createdAt": "2026-05-13T14:55:28.341Z",
        "number": 1
      }
    },
    {
      "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
      "createdAt": "2026-05-13T14:55:28.432Z",
      "id": "98475",
      "parentId": "98422",
      "parentType": "page",
      "spaceId": "98309",
      "status": "current",
      "title": "Template - Meeting notes",
      "version": {
        "createdAt": "2026-05-13T14:55:28.432Z",
        "number": 1
      }
    }
  ],
  "size": 3
}
```

---

## pages get

Fetch a single page by ID. Returns the full raw API response including the page body in storage format.

```
aai-cli confluence pages get <PAGE_ID> --profile confluence-work
```

| Argument | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |

**Example**

```
aai-cli confluence pages get 3964929 --profile confluence-work
```

```json
{
  "_links": {
    "base": "https://marsellewing.atlassian.net/wiki",
    "editui": "/pages/resumedraft.action?draftId=3964929",
    "edituiv2": "/spaces/SD/pages/edit-v2/3964929",
    "tinyui": "/x/AYA8",
    "webui": "/spaces/SD/pages/3964929/aai-cli+skill+doc+test+page+updated"
  },
  "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "body": {
    "storage": {
      "representation": "storage",
      "value": "Updated body content for skill documentation."
    }
  },
  "createdAt": "2026-05-27T07:09:12Z",
  "id": "3964929",
  "lastOwnerId": null,
  "ownerId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "parentId": "98422",
  "parentType": "page",
  "position": 2500,
  "spaceId": "98309",
  "status": "current",
  "title": "aai-cli skill doc test page (updated)",
  "version": {
    "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "createdAt": "2026-05-27T07:13:32.034Z",
    "message": "",
    "minorEdit": false,
    "ncsStepVersion": "10",
    "number": 2
  }
}
```

---

## pages create

Create a new page. Either `--space-key` or `--space-id` must be provided. Use `--json` to pass a full Confluence create body; individual flags override matching JSON fields.

```
aai-cli confluence pages create [--json JSON_OR_PATH] [--space-key KEY] [--space-id ID] --profile confluence-work
                                [--title TEXT] [--body TEXT] [--parent-id ID]
```

| Flag | Required | Description |
|---|---|---|
| `--space-key` | **yes** (unless `--space-id` or `--json` covers it) | Space key, e.g. `SD` |
| `--space-id` | **yes** (unless `--space-key` or `--json` covers it) | Numeric space ID |
| `--title` | **yes** (unless `--json` covers it) | Page title |
| `--body` | no | Page body in Confluence storage format (XML) |
| `--parent-id` | no | Numeric ID of the parent page. Omit to create at space root |
| `--json` | no | Inline JSON string or path to a JSON file. Flags override matching fields |

**Example — with space key, title, body, and parent**

```
aai-cli confluence pages create --space-key SD --title "aai-cli skill doc child page" --body "Child page body." --parent-id 3964929 --profile confluence-work
```

```json
{
  "_links": {
    "base": "https://marsellewing.atlassian.net/wiki",
    "editui": "/pages/resumedraft.action?draftId=4096001",
    "edituiv2": "/spaces/SD/pages/edit-v2/4096001",
    "tinyui": "/x/AYA_/",
    "webui": "/spaces/SD/pages/4096001/aai-cli+skill+doc+child+page"
  },
  "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "body": {
    "storage": {
      "representation": "storage",
      "value": "Child page body."
    }
  },
  "createdAt": "2026-05-27T07:22:53.016Z",
  "id": "4096001",
  "lastOwnerId": null,
  "ownerId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "parentId": "3964929",
  "parentType": "page",
  "position": 621,
  "spaceId": "98309",
  "status": "current",
  "title": "aai-cli skill doc child page",
  "version": {
    "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "createdAt": "2026-05-27T07:22:53.016Z",
    "message": "",
    "minorEdit": false,
    "ncsStepVersion": "1",
    "number": 1
  }
}
```

---

## pages update

Update an existing page. The command auto-fetches the current page version before submitting — you do not need to pass the current version number. Only the flags you pass are changed; omitted flags leave the field untouched.

```
aai-cli confluence pages update <PAGE_ID> [--json JSON_OR_PATH] [--title TEXT] --profile confluence-work
                                [--body TEXT] [--version N]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `PAGE_ID` | **yes** | Numeric page ID |
| `--title` | no | New page title |
| `--body` | no | New body in Confluence storage format |
| `--version` | no | Target version number. Defaults to `current_version + 1` (auto-increment) |
| `--json` | no | Raw Confluence page-update body. Flags override matching fields |

**Example — update title and body**

```
aai-cli confluence pages update 3964929 --title "aai-cli skill doc test page (updated)" --body "Updated body content for skill documentation." --profile confluence-work
```

```json
{
  "_links": {
    "base": "https://marsellewing.atlassian.net/wiki",
    "editui": "/pages/resumedraft.action?draftId=3964929",
    "edituiv2": "/spaces/SD/pages/edit-v2/3964929",
    "tinyui": "/x/AYA8",
    "webui": "/spaces/SD/pages/3964929/aai-cli+skill+doc+test+page+updated"
  },
  "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "body": {
    "storage": {
      "representation": "storage",
      "value": "Updated body content for skill documentation."
    }
  },
  "createdAt": "2026-05-27T07:09:12Z",
  "id": "3964929",
  "ownerId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "parentId": "98422",
  "parentType": "page",
  "spaceId": "98309",
  "status": "current",
  "title": "aai-cli skill doc test page (updated)",
  "version": {
    "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "createdAt": "2026-05-27T07:13:32.034Z",
    "number": 2
  }
}
```

# Confluence Spaces Skill

Commands under `aai-cli confluence spaces`.

---

## spaces list

List Confluence spaces with optional filters. All filter flags are optional and AND-joined. Without any filter, all spaces are returned (up to `--limit`).

Multi-value flags accept comma-separated strings.

```
aai-cli confluence spaces list [--key KEYS] [--type TYPE] [--status STATUS] [--limit N] --profile confluence-work
```

| Flag | Required | Type | Description |
|---|---|---|---|
| `--key` | no | string (csv) | Space key(s) to filter by. E.g. `SD` or `SD,ENG` |
| `--type` | no | string | Space type: `global`, `personal`, `onboarding` |
| `--status` | no | string | Space status: `current` or `archived` |
| `--limit` | no | integer | Max spaces to return. Default: `50` |

**Example — filter by key**

```
aai-cli confluence spaces list --key SD --profile confluence-work
```

```json
{
  "limit": 50,
  "results": [
    {
      "homepageId": "98422",
      "id": "98309",
      "key": "SD",
      "name": "Software Development",
      "status": "current",
      "type": "onboarding"
    }
  ],
  "size": 1
}
```

---

## spaces get

Fetch a single space by key. Returns the full raw API response.

```
aai-cli confluence spaces get <SPACE_KEY> --profile confluence-work
```

| Argument | Required | Description |
|---|---|---|
| `SPACE_KEY` | **yes** | Space key, e.g. `SD` |

**Example**

```
aai-cli confluence spaces get SD --profile confluence-work
```

```json
{
  "_links": {
    "webui": "/spaces/SD"
  },
  "authorId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "createdAt": "2026-05-13T14:55:20.941Z",
  "currentActiveAlias": "SD",
  "description": null,
  "homepageId": "98422",
  "icon": null,
  "id": "98309",
  "key": "SD",
  "name": "Software Development",
  "spaceOwnerId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "status": "current",
  "type": "onboarding"
}
```
""",
    },
]
