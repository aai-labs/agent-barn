"""aai-cli jira skill docs."""

JIRA_SKILLS: list[dict[str, str]] = [
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_skill.md",
        "skill_content": """\
# aai-cli Jira Skill

Agent reference for the `aai-cli jira` command group.

## Required flag

Every command requires `--profile jira-work`. Always include it.

```
aai-cli jira <command> --profile jira-work [other flags]
```
## Response shapes

**List commands** return trimmed responses: UI-only fields (`self`, `expand`, avatar URLs) are stripped. Pagination is resolved internally up to `--limit`. The envelope always includes `isLast`, `maxResults`, and `startAt`/`total` where the API provides them.

**Get commands** return the full raw API response.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "provider_api_error",
  "details": { "errorMessages": ["..."], "errors": {} },
  "message": "provider returned HTTP 400",
  "operation": "issues.list",
  "service": "jira",
  "status": 400
}
```

| Code | Meaning |
|---|---|
| `provider_api_error` | Jira returned 4xx/5xx. Check `status` and `details.errorMessages` |
| `auth` | Authentication failed — missing or invalid token |
| `config` | Missing or malformed config/secrets file |
| `invalid_input` | A required flag was missing or a value was rejected before the API call |
| `network` | Could not reach the Jira host |

Exit code is non-zero on any error.

## Resource reference

Read the file for the resource you need:

| Resource | Commands | File |
|---|---|---|
| Issues | list, get, create, update, comments list/get/create, attachments list/download/upload | [jira_issue_skill/jira_issue_skill.md](jira_issue_skill/jira_issue_skill.md) |
| Projects | list, get | [jira_project_skill/jira_project_skill.md](jira_project_skill/jira_project_skill.md) |
| Sprints | list, get, create, issues add | [jira_sprint_skill/jira_sprint_skill.md](jira_sprint_skill/jira_sprint_skill.md) |
| Boards | list, get | [jira_board_skill/jira_board_skill.md](jira_board_skill/jira_board_skill.md) |
| Users | get | [jira_user_skill/jira_user_skill.md](jira_user_skill/jira_user_skill.md) |
""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_board_skill/jira_board_skill.md",
        "skill_content": """\
# Jira Boards Skill

Commands under `aai-cli jira boards`. For global flags and error shapes see [../jira_skill.md](../jira_skill.md).

---

## boards list

List Agile boards. Returns trimmed board objects (avatar URLs and internal location IDs stripped).

```
aai-cli jira boards list [--type TYPE] [--project KEY] [--name TEXT] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--type` | no | Board type: `scrum`, `kanban`, or `simple` |
| `--project` | no | Filter by project key |
| `--name` | no | Filter by board name (substring match) |
| `--limit` | no | Max boards to return. Default: `50` |

**Example**

```
aai-cli jira boards list --limit 1
```

```json
{
  "isLast": true,
  "maxResults": 1,
  "startAt": 0,
  "total": 1,
  "values": [
    {
      "id": 1,
      "location": {
        "projectKey": "SCRUM",
        "projectName": "test-space",
        "projectTypeKey": "software"
      },
      "name": "SCRUM board",
      "type": "simple"
    }
  ]
}
```

---

## boards get

Fetch a single board by numeric ID. Returns the full raw API response.

```
aai-cli jira boards get <BOARD_ID>
```

| Argument | Required | Description |
|---|---|---|
| `BOARD_ID` | **yes** | Numeric board ID |

**Example**

```
aai-cli jira boards get 1
```

```json
{
  "id": 1,
  "isPrivate": false,
  "location": {
    "avatarURI": "https://marsellewing.atlassian.net/rest/api/2/universal_avatar/...",
    "displayName": "test-space (SCRUM)",
    "name": "test-space (SCRUM)",
    "projectId": 10000,
    "projectKey": "SCRUM",
    "projectName": "test-space",
    "projectTypeKey": "software"
  },
  "name": "SCRUM board",
  "self": "https://marsellewing.atlassian.net/rest/agile/1.0/board/1",
  "type": "simple"
}
```
""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_issue_skill/jira_issue_skill.md",
        "skill_content": """\
# Jira Issues Skill

Commands under `aai-cli jira issues`. For global flags and error shapes see [../jira_skill.md](../jira_skill.md).

---

## issues list

List issues with structured filters. All filter flags are optional and AND-joined. Omitting all filters returns a Jira error (unbounded queries are blocked by the API) — provide at least one filter flag.

Multi-value flags accept comma-separated strings.

```
aai-cli jira issues list [--project KEY] [--status NAMES] [--assignee me|ACCOUNT_ID]
                         [--type NAMES] [--sprint current|future|closed|ID]
                         [--text TEXT] [--updated-since DATE_OR_RELATIVE]
                         [--fields FIELD_LIST] [--limit N]
```

| Flag | Required | Type | Description |
|---|---|---|---|
| `--project` | no | string | Project key, e.g. `SCRUM` |
| `--status` | no | string (csv) | Status name(s). Single: `"To Do"`. Multi: `"To Do,In Progress"` |
| `--assignee` | no | string | `me` expands to `currentUser()`. Otherwise an account ID |
| `--type` | no | string (csv) | Issue type name(s), e.g. `Task` or `Bug,Task` |
| `--sprint` | no | string | `current` (open sprints), `future`, `closed`, or a numeric sprint ID |
| `--text` | no | string | Full-text search across summary, description, and comments |
| `--updated-since` | no | string | Relative: `7d`, `30d`, `1y`. Absolute ISO date: `2026-05-01` |
| `--fields` | no | string (csv) | Jira field names to include. Default: `key,summary,status,issuetype,assignee,created,updated,description,project` |
| `--limit` | no | integer | Max issues to return. Default: `50` |

**Example — project + multi-status filter**

```
aai-cli jira issues list --project SCRUM --status "To Do,In Progress" --limit 1
```

```json
{
  "isLast": true,
  "issues": [
    {
      "fields": {
        "assignee": null,
        "created": "2026-05-13T17:37:04.821+0300",
        "description": null,
        "issuetype": { "name": "Subtask", "subtask": true },
        "project": { "key": "SCRUM", "name": "test-space" },
        "status": { "name": "To Do", "statusCategory": { "name": "To Do" } },
        "summary": "Subtask 2.1",
        "updated": "2026-05-13T17:37:05.226+0300"
      },
      "id": "10003",
      "key": "SCRUM-4"
    }
  ],
  "maxResults": 1
}
```

**Example — current sprint**

```
aai-cli jira issues list --sprint current --limit 1
```

```json
{
  "isLast": true,
  "issues": [
    {
      "fields": {
        "assignee": null,
        "created": "2026-05-13T17:37:03.695+0300",
        "description": null,
        "issuetype": { "name": "Story", "subtask": false },
        "project": { "key": "SCRUM", "name": "test-space" },
        "status": { "name": "In Progress", "statusCategory": { "name": "In Progress" } },
        "summary": "Task 2",
        "updated": "2026-05-13T17:37:05.638+0300"
      },
      "id": "10001",
      "key": "SCRUM-2"
    }
  ],
  "maxResults": 1
}
```

---

## issues get

Fetch a single issue by key or numeric ID. Returns the full raw API response including all fields, comments, and changelog.

```
aai-cli jira issues get <ISSUE_KEY_OR_ID>
```

| Argument | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key (`SCRUM-1`) or numeric ID (`10000`) |

**Example**

```
aai-cli jira issues get SCRUM-1
```

```json
{
  "expand": "renderedFields,names,schema,operations,editmeta,changelog,versionedRepresentations",
  "fields": {
    "assignee": null,
    "comment": {
      "comments": [
        {
          "author": {
            "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
            "displayName": "Marselle Wing",
            "emailAddress": "marsellewing@gmail.com"
          },
          "body": {
            "content": [
              {
                "content": [{ "text": "This is a test comment from aai-cli.", "type": "text" }],
                "type": "paragraph"
              }
            ],
            "type": "doc",
            "version": 1
          },
          "created": "2026-05-19T14:56:55.744+0300",
          "id": "10001"
        }
      ],
      "total": 2
    },
    "description": null,
    "issuetype": { "name": "Task", "subtask": false },
    "project": { "key": "SCRUM", "name": "test-space" },
    "status": { "name": "To Do", "statusCategory": { "name": "To Do" } },
    "summary": "Task 1"
  },
  "id": "10000",
  "key": "SCRUM-1"
}
```

---

## issues create

Create a new issue. `--project` and `--summary` are the minimal required flags. Use `--json` to pass a full Jira create body; individual flags override matching JSON fields.

```
aai-cli jira issues create [--json JSON_OR_PATH] [--project KEY] [--summary TEXT]
                           [--description TEXT] [--issue-type NAME]
```

| Flag | Required | Description |
|---|---|---|
| `--project` | **yes** (unless `--json` covers it) | Project key, e.g. `SCRUM` |
| `--summary` | **yes** (unless `--json` covers it) | Issue summary line |
| `--description` | no | Description text. Auto-converted to Atlassian Document Format (ADF) |
| `--issue-type` | no | Issue type name. Defaults to `Task` |
| `--json` | no | Inline JSON string or path to a JSON file (`-` for stdin). Flags override matching fields |

**Example**

```
aai-cli jira issues create --project SCRUM --summary "Fix login timeout" --description "Users are logged out after 5 minutes of inactivity"
```

```json
{
  "id": "10010",
  "key": "SCRUM-11",
  "self": "https://example.atlassian.net/rest/api/3/issue/10010"
}
```

---

## issues update

Update an existing issue. Only the flags you pass are changed; omitted flags leave the field untouched.

```
aai-cli jira issues update <ISSUE_KEY_OR_ID> [--json JSON_OR_PATH]
                           [--summary TEXT] [--description TEXT]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |
| `--summary` | no | New summary text |
| `--description` | no | New description (auto-converted to ADF) |
| `--json` | no | Raw Jira issue-update body. Flags override matching fields |

**Example**

```
aai-cli jira issues update SCRUM-11 --summary "Fix login timeout (critical)"
```

```json
{}
```

An empty `{}` response means success.

---

## issues comments list

List comments on an issue. Returns trimmed comment objects (avatar URLs stripped).

```
aai-cli jira issues comments list <ISSUE_KEY_OR_ID> [--limit N]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |
| `--limit` | no | Max comments to return. Default: `50` |

**Example**

```
aai-cli jira issues comments list SCRUM-1 --limit 1
```

```json
{
  "comments": [
    {
      "author": {
        "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
        "displayName": "Marselle Wing",
        "emailAddress": "marsellewing@gmail.com"
      },
      "body": {
        "content": [
          {
            "content": [{ "text": "This is a test comment from aai-cli.", "type": "text" }],
            "type": "paragraph"
          }
        ],
        "type": "doc",
        "version": 1
      },
      "created": "2026-05-19T14:56:55.744+0300",
      "id": "10001",
      "jsdPublic": true,
      "updateAuthor": {
        "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
        "displayName": "Marselle Wing",
        "emailAddress": "marsellewing@gmail.com"
      },
      "updated": "2026-05-19T14:56:55.744+0300"
    }
  ],
  "maxResults": 1,
  "startAt": 0,
  "total": 2
}
```

---

## issues comments get

Fetch a single comment by ID. Returns the full raw API response.

```
aai-cli jira issues comments get <ISSUE_KEY_OR_ID> <COMMENT_ID>
```

| Argument | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |
| `COMMENT_ID` | **yes** | Numeric comment ID |

**Example**

```
aai-cli jira issues comments get SCRUM-1 10001
```

```json
{
  "author": {
    "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "accountType": "atlassian",
    "active": true,
    "displayName": "Marselle Wing",
    "emailAddress": "marsellewing@gmail.com",
    "timeZone": "Africa/Addis_Ababa"
  },
  "body": {
    "content": [
      {
        "content": [{ "text": "This is a test comment from aai-cli.", "type": "text" }],
        "type": "paragraph"
      }
    ],
    "type": "doc",
    "version": 1
  },
  "created": "2026-05-19T14:56:55.744+0300",
  "id": "10001",
  "jsdPublic": true,
  "updated": "2026-05-19T14:56:55.744+0300"
}
```

---

## issues comments create

Add a comment to an issue. Use `--body` for plain text (auto-converted to ADF), or `--json` for pre-built ADF content.

```
aai-cli jira issues comments create <ISSUE_KEY_OR_ID> [--body TEXT] [--json JSON_OR_PATH]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |
| `--body` | **yes** (unless `--json` covers it) | Plain text body. Auto-converted to ADF. Overrides `body` inside `--json` if both are given |
| `--json` | no | Raw Jira comment body JSON |

**Example**

```
aai-cli jira issues comments create SCRUM-1 --body "Confirmed fix is deployed to staging."
```

```json
{
  "author": {
    "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
    "displayName": "Marselle Wing",
    "emailAddress": "marsellewing@gmail.com"
  },
  "body": {
    "content": [
      {
        "content": [{ "text": "Confirmed fix is deployed to staging.", "type": "text" }],
        "type": "paragraph"
      }
    ],
    "type": "doc",
    "version": 1
  },
  "created": "2026-05-19T15:10:00.000+0300",
  "id": "10002",
  "jsdPublic": true
}
```

---

## issues attachments list

List attachments on an issue. Returns trimmed attachment objects (avatar URLs and self-links stripped).

```
aai-cli jira issues attachments list <ISSUE_KEY_OR_ID>
```

| Argument | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |

**Example**

```
aai-cli jira issues attachments list SCRUM-1
```

```json
{
  "attachments": [
    {
      "author": {
        "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
        "displayName": "Marselle Wing"
      },
      "created": "2026-05-27T10:01:11.133+0300",
      "filename": "jira_smoke.txt",
      "id": "10000",
      "mimeType": "text/plain",
      "size": 33
    }
  ],
  "total": 1
}
```

Use `id` from this response as `<ATTACHMENT_ID>` in the download command.

---

## issues attachments download

Download an attachment's binary content to a local file.

```
aai-cli jira issues attachments download <ATTACHMENT_ID> --output <PATH>
```

| Argument / Flag | Required | Description |
|---|---|---|
| `ATTACHMENT_ID` | **yes** | Numeric attachment ID (from `attachments list`) |
| `--output` | **yes** | Local file path to write the downloaded content |

**Example**

```
aai-cli jira issues attachments download 10000 --output /tmp/jira_smoke.txt
```

```json
{
  "bytes": 33,
  "output": "/tmp/jira_smoke.txt"
}
```

---

## issues attachments upload

Upload a local file as an attachment to an issue.

```
aai-cli jira issues attachments upload <ISSUE_KEY_OR_ID> --file <PATH>
```

| Argument / Flag | Required | Description |
|---|---|---|
| `ISSUE_KEY_OR_ID` | **yes** | Issue key or numeric ID |
| `--file` | **yes** | Local file path to upload |

Returns an array of attachment objects (raw Jira response). On success there will be exactly one element matching the uploaded file.

**Example**

```
aai-cli jira issues attachments upload SCRUM-1 --file /tmp/report.pdf
```

```json
[
  {
    "author": {
      "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
      "displayName": "Marselle Wing",
      "emailAddress": "marsellewing@gmail.com"
    },
    "content": "https://example.atlassian.net/rest/api/2/attachment/content/10000",
    "created": "2026-05-27T10:01:11.133+0300",
    "filename": "report.pdf",
    "id": "10000",
    "mimeType": "application/pdf",
    "size": 204800
  }
]
```
""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_project_skill/jira_project_skill.md",
        "skill_content": """\
# Jira Projects Skill

Commands under `aai-cli jira projects`. For global flags and error shapes see [../jira_skill.md](../jira_skill.md).

---

## projects list

List all projects in the Jira site. Returns trimmed objects (avatar URLs and self links stripped).

```
aai-cli jira projects list [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--limit` | no | Max projects to return. Default: `50` |

**Example**

```
aai-cli jira projects list
```

```json
{
  "isLast": true,
  "maxResults": 50,
  "startAt": 0,
  "total": 1,
  "values": [
    {
      "id": "10000",
      "isPrivate": false,
      "key": "SCRUM",
      "name": "test-space",
      "projectTypeKey": "software"
    }
  ]
}
```

---

## projects get

Fetch a single project by key or numeric ID. Returns the full raw API response including issue types, lead, and all metadata.

```
aai-cli jira projects get <PROJECT_KEY_OR_ID>
```

| Argument | Required | Description |
|---|---|---|
| `PROJECT_KEY_OR_ID` | **yes** | Project key (e.g. `SCRUM`) or numeric ID |

**Example**

```
aai-cli jira projects get SCRUM
```

```json
{
  "assigneeType": "UNASSIGNED",
  "description": "Your first project",
  "id": "10000",
  "isPrivate": false,
  "issueTypes": [
    { "hierarchyLevel": 1, "id": "10001", "name": "Epic", "subtask": false },
    { "hierarchyLevel": -1, "id": "10005", "name": "Subtask", "subtask": true },
    { "hierarchyLevel": 0, "id": "10003", "name": "Task", "subtask": false }
  ],
  "key": "SCRUM",
  "name": "test-space",
  "projectTypeKey": "software",
  "style": "classic"
}
```
""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_sprint_skill/jira_sprint_skill.md",
        "skill_content": """\
# Jira Sprints Skill

Commands under `aai-cli jira sprints`. For global flags and error shapes see [../jira_skill.md](../jira_skill.md).

---

## sprints list

List sprints for a board. Returns trimmed sprint objects. Future sprints omit `startDate`/`endDate` until scheduled.

```
aai-cli jira sprints list --board BOARD_ID [--state STATE] [--limit N]
```

| Flag | Required | Description |
|---|---|---|
| `--board` | **yes** | Numeric board ID |
| `--state` | no | Filter by state: `active`, `future`, or `closed` |
| `--limit` | no | Max sprints to return. Default: `50` |

**Example — active sprints only**

```
aai-cli jira sprints list --board 1 --state active
```

```json
{
  "isLast": true,
  "maxResults": 50,
  "startAt": 0,
  "total": 1,
  "values": [
    {
      "endDate": "2026-05-27T14:37:05.363Z",
      "id": 2,
      "name": "SCRUM Sprint 0",
      "originBoardId": 1,
      "startDate": "2026-05-13T14:37:05.363Z",
      "state": "active"
    }
  ]
}
```

**Example — all sprints (mixed states)**

```
aai-cli jira sprints list --board 1 --limit 2
```

```json
{
  "isLast": false,
  "maxResults": 2,
  "startAt": 0,
  "total": 4,
  "values": [
    {
      "endDate": "2026-05-27T14:37:05.363Z",
      "id": 2,
      "name": "SCRUM Sprint 0",
      "originBoardId": 1,
      "startDate": "2026-05-13T14:37:05.363Z",
      "state": "active"
    },
    {
      "createdDate": "2026-05-13T14:37:02.815Z",
      "id": 1,
      "name": "SCRUM Sprint 1",
      "originBoardId": 1,
      "state": "future"
    }
  ]
}
```

---

## sprints get

Fetch a single sprint by numeric ID. Returns the full raw API response.

```
aai-cli jira sprints get <SPRINT_ID>
```

| Argument | Required | Description |
|---|---|---|
| `SPRINT_ID` | **yes** | Numeric sprint ID |

**Example**

```
aai-cli jira sprints get 2
```

```json
{
  "endDate": "2026-05-27T14:37:05.363Z",
  "id": 2,
  "name": "SCRUM Sprint 0",
  "originBoardId": 1,
  "self": "https://marsellewing.atlassian.net/rest/agile/1.0/sprint/2",
  "startDate": "2026-05-13T14:37:05.363Z",
  "state": "active"
}
```

---

## sprints create

Create a new sprint on a board. `--board` and `--name` are required unless a complete body is passed via `--json`.

```
aai-cli jira sprints create [--json JSON_OR_PATH] --board BOARD_ID --name TEXT
                            [--goal TEXT] [--start-date ISO_8601] [--end-date ISO_8601]
```

| Flag | Required | Description |
|---|---|---|
| `--board` | **yes** (unless `--json` covers `originBoardId`) | Numeric board ID |
| `--name` | **yes** (unless `--json` covers `name`) | Sprint name |
| `--goal` | no | Sprint goal text |
| `--start-date` | no | ISO 8601 datetime, e.g. `2026-06-01T00:00:00.000Z` |
| `--end-date` | no | ISO 8601 datetime |
| `--json` | no | Raw Jira sprint-create body. Flags override matching fields |

**Example**

```
aai-cli jira sprints create --board 1 --name "Sprint 5" --goal "Ship auth v2" --start-date 2026-06-01T00:00:00.000Z --end-date 2026-06-14T00:00:00.000Z
```

```json
{
  "id": 7,
  "name": "Sprint 5",
  "originBoardId": 1,
  "self": "https://marsellewing.atlassian.net/rest/agile/1.0/sprint/7",
  "state": "future"
}
```

---

## sprints issues add

Move one or more issues into a sprint.

```
aai-cli jira sprints issues add <SPRINT_ID> --issues KEY1[,KEY2,...]
```

| Argument / Flag | Required | Description |
|---|---|---|
| `SPRINT_ID` | **yes** | Numeric sprint ID |
| `--issues` | **yes** | Comma-separated issue keys, e.g. `SCRUM-1,SCRUM-2` |

**Example**

```
aai-cli jira sprints issues add 2 --issues SCRUM-5,SCRUM-6
```

```json
{}
```

An empty `{}` response means success.
""",
    },
    {
        "skill_name": "aai-cli",
        "skill_file_path": "aai-cli/jira_skill/jira_user_skill/jira_user_skill.md",
        "skill_content": """\
# Jira Users Skill

Commands under `aai-cli jira users`. For global flags and error shapes see [../jira_skill.md](../jira_skill.md).

---

## users get

Fetch a user profile by Atlassian account ID. Returns the full raw API response.

```
aai-cli jira users get <ACCOUNT_ID>
```

| Argument | Required | Description |
|---|---|---|
| `ACCOUNT_ID` | **yes** | Atlassian account ID (format: `712020:uuid`) |

To find the account ID for the authenticated user, run `aai-cli jira issues list --assignee me` and inspect `fields.assignee.accountId` on any returned issue, or look at `author.accountId` inside any comment returned by `issues comments list`.

**Example**

```
aai-cli jira users get 712020:3fd582db-3261-4930-b192-171d1cb74d1f
```

```json
{
  "accountId": "712020:3fd582db-3261-4930-b192-171d1cb74d1f",
  "accountType": "atlassian",
  "active": true,
  "displayName": "Marselle Wing",
  "emailAddress": "marsellewing@gmail.com",
  "timeZone": "Africa/Addis_Ababa"
}
```
""",
    },
]
