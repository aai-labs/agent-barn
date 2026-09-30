# aai-cli Google Drive Skill

Agent reference for the `aai-cli drive` command group.

## Required flag

Every command needs a Drive profile. Pass it explicitly unless the default profile is already known to be the right one.

```
aai-cli drive <resource> <action> [args] --profile google-drive-work
```

A Drive profile is an ordinary Google REST profile:

```toml
[profiles.google-drive-work]
provider = "google"
auth_type = "bearer_token"
token_secret = "google.drive_access_token"
# or, for long-running use:
# refresh_token_secret = "google.drive_refresh_token"
# client_id = "..."
# client_secret_secret = "google.oauth_client_secret"
```

Required OAuth scope: `https://www.googleapis.com/auth/drive.readonly` for everything except `files upload`, which needs `https://www.googleapis.com/auth/drive.file` (files this app created) or `https://www.googleapis.com/auth/drive`. `drive.metadata.readonly` is enough for `files list`/`files get`/`folders`/`drives`/`permissions` but **not** for `files download`.

## Command summary

```
aai-cli drive files list [--parent ID] [--drive-id ID] [--name-contains TEXT] [--mime-type MIME] [--q CLAUSE] [--order-by SPEC] [--fields PROJECTION] [--include-trashed] [--limit N] [--page-token TOKEN]
aai-cli drive files get <FILE_ID> [--fields PROJECTION]
aai-cli drive files download <FILE_ID> --output PATH [--mime-type MIME]
aai-cli drive files upload <FILE> [--name NAME] [--parent ID] [--mime-type MIME] [--description TEXT]
aai-cli drive folders list [--parent ID] [--drive-id ID] [--name-contains TEXT] [--limit N] [--page-token TOKEN]
aai-cli drive folders get <FOLDER_ID> [--fields PROJECTION]
aai-cli drive drives list [--limit N] [--page-token TOKEN]
aai-cli drive drives get <DRIVE_ID>
aai-cli drive permissions list <FILE_ID> [--limit N] [--page-token TOKEN]
aai-cli drive permissions get <FILE_ID> <PERMISSION_ID>
aai-cli drive about get
```

There is no write command other than `files upload`. Renaming, moving, trashing, deleting, and sharing are intentionally absent.

## Things Drive does that will surprise you

**Field projections are mandatory in practice.** Drive's default response is only `kind`, `id`, `name`, `mimeType`, and `resourceKey` — no size, no timestamps, no parents, no link. Every `aai-cli` command sends an explicit `fields` projection, so the responses below are richer than raw Drive defaults. `--fields` replaces the projection when you want something else.

**Shared drives are opt-in at the API level.** Every listing sends `supportsAllDrives=true`, `includeItemsFromAllDrives=true`, and `corpora=allDrives`, so shared-drive content is present. Without those, Drive returns a successful response that silently omits it. Pass `--drive-id` to narrow to one shared drive (`corpora=drive`).

**Google-native docs have no bytes.** `application/vnd.google-apps.*` files (Docs, Sheets, Slides, Forms, …) cannot be fetched with `alt=media`; they must be exported to a concrete format. `files download` detects this and exports automatically. They also report **no `size` field**, and exports are capped at 10 MB by Google — a too-large document fails at download time with `exportSizeLimitExceeded`, not before.

**Folders are files.** A folder is a file whose `mimeType` is `application/vnd.google-apps.folder`. `folders list` is `files list` with that filter applied; `folders get` is `files get`.

**Trashed files are hidden by default.** Listings add `trashed = false`. Pass `--include-trashed` to see them.

## Response shapes

**`files list` / `folders list`** return `{ "files": [...], "incompleteSearch": false, "nextPageToken": "..." }`. Each file carries `id`, `name`, `mimeType`, `size` (absent for native docs and folders), `createdTime`, `modifiedTime`, `parents`, `driveId` (present only for shared-drive items), `trashed`, `webViewLink`, and `owners`. `id` is the `FILE_ID` used by every other command. A present `nextPageToken` means there is more beyond `--limit`; `_aai.pagination.next_command` shows how to get it.

**`files get` / `folders get`** return one file resource, adding `md5Checksum`, `shared`, `description`, `webContentLink`, `lastModifyingUser`, `capabilities`, `shortcutDetails`, and `exportLinks` (the ready-made export URLs for a native doc).

**`files download`** returns CLI metadata, never content:

```json
{
  "output": "./Q3 Plan.docx",
  "bytes": 24713,
  "file_id": "1XyZ...",
  "name": "Q3 Plan",
  "mime_type": "application/vnd.google-apps.document",
  "exported_mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
```

`exported_mime_type` is `null` for an ordinary blob, which was streamed byte-for-byte.

**`files upload`** returns the created Drive file resource: `id`, `name`, `mimeType`, `size`, `parents`, `driveId`, `createdTime`, `modifiedTime`, `webViewLink`, `webContentLink`. Give the user the `webViewLink`.

**`drives list`** returns `{ "drives": [ { "id", "name", "createdTime", "hidden" } ], "nextPageToken": "..." }`. The `id` of a shared drive is also usable as a `--parent` (its root) and as `--drive-id`.

**`permissions list`** returns `{ "permissions": [ { "id", "type", "role", "emailAddress", "domain", "displayName", "allowFileDiscovery", "deleted", "pendingOwner" } ] }`. `type` is `user`, `group`, `domain`, or `anyone`; `role` is `owner`, `organizer`, `fileOrganizer`, `writer`, `commenter`, or `reader`. A `type: "anyone"` entry means the file is link-shared publicly.

**`about get`** returns `user`, `storageQuota` (`limit`, `usage`, `usageInDrive`, `usageInDriveTrash`), `exportFormats` (every native MIME type mapped to the targets it can convert to), `maxUploadSize`, and `canCreateDrives`.

## Error response shape

All errors print to stderr as a single JSON line:

```json
{
  "code": "auth_error",
  "details": { "error": { "code": 403, "message": "Insufficient Permission", "status": "PERMISSION_DENIED" } },
  "message": "provider returned HTTP 403",
  "operation": "files.download",
  "service": "drive",
  "status": 403
}
```

| Code | Meaning |
|---|---|
| `not_found` | No such file ID, or the token's identity cannot see it. Drive returns 404 for both |
| `auth_error` | 401/403 — expired token, or a scope that does not cover this call |
| `provider_api_error` | Any other 4xx/5xx. Check `status` and `details.error.message` |
| `invalid_input` | A flag was missing or malformed, or the target cannot have content (a folder or a shortcut) |
| `rate_limited` | 429 — back off and retry |

Exit code is non-zero on any error.

---

## files list

Find files and read their metadata.

```
aai-cli drive files list [flags] --profile google-drive-work
```

| Flag | Required | Description |
|---|---|---|
| `--parent` | no | Only direct children of this folder ID |
| `--drive-id` | no | Restrict the search to one shared drive |
| `--name-contains` | no | Substring match on the file name |
| `--mime-type` | no | Exact MIME type match |
| `--q` | no | Raw Drive query clause, ANDed with the rest |
| `--order-by` | no | Drive sort spec, e.g. `modifiedTime desc`, `folder,name` |
| `--fields` | no | Per-file projection, e.g. `id,name,size`. Replaces the default |
| `--include-trashed` | no | Include trashed files (excluded by default) |
| `--limit` | no | Aggregate pages up to this many files. Default 50 |
| `--page-token` | no | `nextPageToken` from a previous response |

**Example — what changed recently in one folder**

```
aai-cli drive files list --parent 1AbCdEfGhIjKlMnOpQrStUvWxYz \
  --order-by "modifiedTime desc" --limit 3 --profile google-drive-work
```

```json
{
  "files": [
    {
      "id": "1XyZ0aBcDeFgHiJkLmNoPqRsTuVwXyZ",
      "name": "Q3 Plan",
      "mimeType": "application/vnd.google-apps.document",
      "createdTime": "2026-07-02T09:14:11.302Z",
      "modifiedTime": "2026-08-11T16:41:55.870Z",
      "parents": ["1AbCdEfGhIjKlMnOpQrStUvWxYz"],
      "trashed": false,
      "webViewLink": "https://docs.google.com/document/d/1XyZ0aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit?usp=drivesdk",
      "owners": [{ "displayName": "Ada Lovelace", "emailAddress": "ada@example.com" }]
    },
    {
      "id": "1QqR2sTuVwXyZ0aBcDeFgHiJkLmNoPq",
      "name": "pricing-2026.csv",
      "mimeType": "text/csv",
      "size": "18422",
      "createdTime": "2026-08-04T11:02:47.115Z",
      "modifiedTime": "2026-08-04T11:02:47.115Z",
      "parents": ["1AbCdEfGhIjKlMnOpQrStUvWxYz"],
      "trashed": false,
      "webViewLink": "https://drive.google.com/file/d/1QqR2sTuVwXyZ0aBcDeFgHiJkLmNoPq/view?usp=drivesdk",
      "owners": [{ "displayName": "Ada Lovelace", "emailAddress": "ada@example.com" }]
    }
  ],
  "incompleteSearch": false,
  "nextPageToken": "~!!~AI9FV7Tz..."
}
```

`size` is a **string** in Drive responses, and is absent for native docs and folders.

**Example — search by name across everything, including shared drives**

```
aai-cli drive files list --name-contains "onboarding" --limit 10 --profile google-drive-work
```

**Example — a filter aai-cli has no flag for**

```
aai-cli drive files list --q "modifiedTime > '2026-08-01T00:00:00'" --limit 20 --profile google-drive-work
```

`--q` is combined with the other filters using `and`, so this still excludes trashed files. Drive's query grammar is documented under "Search for files and folders" in the Drive API docs.

---

## files get

Full metadata for one file.

```
aai-cli drive files get <FILE_ID> [--fields PROJECTION] --profile google-drive-work
```

Use this before `files download` when you need to know whether the file is native (check `mimeType`) or how large it is (check `size`).

---

## files download

Write file content to a local path.

```
aai-cli drive files download <FILE_ID> --output PATH [--mime-type MIME] --profile google-drive-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `FILE_ID` | **yes** | From `files list` |
| `--output` | **yes** | Local path to write. Parent directories are created |
| `--mime-type` | no | Export target for a native doc. Ignored for ordinary blobs |

The command looks up the file's MIME type first, then picks the mechanism:

| File | Mechanism | Default target |
|---|---|---|
| Ordinary blob (PDF, CSV, PNG, .xlsx, …) | `files.get?alt=media` | byte-for-byte |
| Google Docs | `files.export` | `.docx` |
| Google Sheets | `files.export` | `.xlsx` |
| Google Slides | `files.export` | `.pptx` |
| Google Drawings | `files.export` | `image/png` |
| Apps Script | `files.export` | `application/vnd.google-apps.script+json` |
| Other native types | `files.export` | `application/pdf` |
| Folder | — | `invalid_input`; list its children instead |
| Shortcut | — | `invalid_input` naming the target ID to download instead |

**Example — a Google Doc as PDF instead of .docx**

```
aai-cli drive files download 1XyZ0aBcDeFgHiJkLmNoPqRsTuVwXyZ \
  --output ./q3-plan.pdf --mime-type application/pdf --profile google-drive-work
```

Run `aai-cli drive about get` to see exactly which targets a native type supports (`exportFormats`).

---

## files upload

Create a new Drive file from a local file. This is the only write in the group.

```
aai-cli drive files upload <FILE> [--name NAME] [--parent ID] [--mime-type MIME] [--description TEXT] --profile google-drive-work
```

| Argument / Flag | Required | Description |
|---|---|---|
| `FILE` | **yes** | Local path to upload |
| `--name` | no | Drive file name. Defaults to the local file name |
| `--parent` | no | Destination folder ID (or shared drive ID). Defaults to My Drive root |
| `--mime-type` | no | Content type. Guessed from the extension when omitted |
| `--description` | no | Description stored on the file |

The upload protocol is chosen from the payload size and is not a flag: a metadata+media multipart upload up to 5 MB, a resumable session above it. Both produce the same response.

**Example**

```
aai-cli drive files upload ./summary.md --parent 1AbCdEfGhIjKlMnOpQrStUvWxYz --profile google-drive-work
```

```json
{
  "id": "1NeW0aBcDeFgHiJkLmNoPqRsTuVwXyZ",
  "name": "summary.md",
  "mimeType": "text/markdown",
  "size": "2841",
  "parents": ["1AbCdEfGhIjKlMnOpQrStUvWxYz"],
  "createdTime": "2026-08-17T10:22:04.117Z",
  "modifiedTime": "2026-08-17T10:22:04.117Z",
  "webViewLink": "https://drive.google.com/file/d/1NeW0aBcDeFgHiJkLmNoPqRsTuVwXyZ/view?usp=drivesdk"
}
```

Uploading does **not** convert to a Google format — a `.md` stays a Markdown blob, a `.xlsx` stays an Office file. Give the user the `webViewLink`.

Upload creates a new file every time; it never replaces one. Re-running it produces a second file with the same name, which Drive allows.

---

## folders list

Browse the folder tree.

```
aai-cli drive folders list [--parent ID] [--drive-id ID] [--name-contains TEXT] [--limit N] [--page-token TOKEN] --profile google-drive-work
```

Same response shape as `files list`; every entry has `mimeType: "application/vnd.google-apps.folder"`, no `size`, and results are ordered by name. Omit `--parent` to list folders anywhere the token can see.

**Example — walk down one level**

```
aai-cli drive folders list --parent 1AbCdEfGhIjKlMnOpQrStUvWxYz --profile google-drive-work
```

---

## folders get

```
aai-cli drive folders get <FOLDER_ID> [--fields PROJECTION] --profile google-drive-work
```

Same response as `files get`. Useful for resolving a folder's `name` and `parents` when all you have is an ID from a file's `parents` array.

---

## drives list

List the shared drives the token's identity is a member of. Needed to target a shared drive by ID at all.

```
aai-cli drive drives list [--limit N] [--page-token TOKEN] --profile google-drive-work
```

```json
{
  "drives": [
    { "id": "0ABcDeFgHiJkLmNoPqR", "name": "Engineering", "createdTime": "2025-03-11T08:00:00.000Z", "hidden": false }
  ]
}
```

An empty `drives` array means the account has no shared drives (or the plan does not include them) — it does not mean the call failed. Files in My Drive still list normally.

---

## drives get

```
aai-cli drive drives get <DRIVE_ID> --profile google-drive-work
```

Adds `orgUnitId`, `restrictions` (`domainUsersOnly`, `driveMembersOnly`, `copyRequiresWriterPermission`, `adminManagedRestrictions`), and `capabilities` (what this identity may do in the drive).

---

## permissions list

Answer "who can see this file". Read-only.

```
aai-cli drive permissions list <FILE_ID> [--limit N] [--page-token TOKEN] --profile google-drive-work
```

```json
{
  "permissions": [
    { "id": "12345678901234567890", "type": "user", "role": "owner", "emailAddress": "ada@example.com", "displayName": "Ada Lovelace", "deleted": false, "pendingOwner": false },
    { "id": "09876543210987654321", "type": "user", "role": "writer", "emailAddress": "grace@example.com", "displayName": "Grace Hopper", "deleted": false },
    { "id": "anyoneWithLink", "type": "anyone", "role": "reader", "allowFileDiscovery": false }
  ]
}
```

Listing permissions needs write-ish access to the file in Drive's model: a `reader` on someone else's file gets `403 insufficientFilePermissions` here even though `files get` succeeded. That is Drive's rule, not a CLI limitation.

---

## permissions get

```
aai-cli drive permissions get <FILE_ID> <PERMISSION_ID> --profile google-drive-work
```

`PERMISSION_ID` comes from `permissions list`.

---

## about get

Storage quota and the conversions Drive supports.

```
aai-cli drive about get --profile google-drive-work
```

```json
{
  "user": { "displayName": "Ada Lovelace", "emailAddress": "ada@example.com", "kind": "drive#user" },
  "storageQuota": { "limit": "16106127360", "usage": "4820117905", "usageInDrive": "1204518110", "usageInDriveTrash": "18422" },
  "maxUploadSize": "5497558138880",
  "canCreateDrives": false,
  "exportFormats": {
    "application/vnd.google-apps.document": [
      "application/rtf",
      "application/vnd.oasis.opendocument.text",
      "text/html",
      "application/pdf",
      "application/epub+zip",
      "application/zip",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "text/plain",
      "application/vnd.google-apps.document.markdown",
      "text/markdown"
    ]
  }
}
```

Quota values are **strings** of bytes. A missing `limit` means unlimited storage. Use `exportFormats` to check a `--mime-type` before passing it to `files download`.

---

## Typical agent flows

**"Read the doc in this folder called Q3 Plan"**

```
aai-cli drive files list --parent <FOLDER_ID> --name-contains "Q3 Plan" --limit 5 --profile google-drive-work
aai-cli drive files download <FILE_ID> --output ./q3-plan.docx --profile google-drive-work
```

**"Is this spreadsheet shared outside the company?"**

```
aai-cli drive permissions list <FILE_ID> --profile google-drive-work
```

Look for `type: "anyone"`, or `type: "domain"` / `emailAddress` values outside your domain.

**"Hand me back the report you generated"**

```
aai-cli drive files upload ./report.xlsx --parent <FOLDER_ID> --profile google-drive-work
```

Then give the user the `webViewLink` from the response.

**"Find the file — I only know it's somewhere in the Engineering shared drive"**

```
aai-cli drive drives list --profile google-drive-work
aai-cli drive files list --drive-id <DRIVE_ID> --name-contains "runbook" --limit 20 --profile google-drive-work
```
