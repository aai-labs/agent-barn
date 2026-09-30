# Microsoft 365 concepts and service routing

Use this reference to decide *where* work belongs and which identifiers/auth context are needed. Use the [command reference](command-reference.md) afterward for exact syntax.

## The practical mental model

```text
Microsoft Entra tenant
├── users
│   ├── Exchange mailbox → messages, calendar events, contacts
│   ├── OneDrive          → the user's work files
│   └── Microsoft To Do   → the user's task lists and tasks
└── Microsoft 365 groups
    ├── Teams team        → channels, members, conversations
    ├── SharePoint site   → document libraries and structured lists
    └── Planner plans     → buckets and shared tasks
```

This is a routing model, not a claim that every resource must have exactly one parent. SharePoint sites can exist without Teams, users can share OneDrive files, and Microsoft 365 services expose additional relationships not covered by the CLI.

Microsoft Graph is the API gateway across these services. It does not make their IDs interchangeable or erase their authorization boundaries.

## Decide by ownership and collaboration shape

| User intent | Use | Why |
| --- | --- | --- |
| Send/read mail, schedule a meeting, manage address-book entries | Outlook mail/calendar/contacts | These live in an Exchange mailbox and are scoped to a user |
| Store or stage a document for one user | OneDrive | The drive belongs to that user |
| Store a document for a department, project, or Team | SharePoint document library | Shared ownership and lifecycle belong to the site, not one employee |
| Track structured records with columns and status fields | SharePoint list | A list item is a row-like record; it is not a document upload |
| Read a Team's channels, members, or discussion messages | Teams | These are collaboration/conversation resources |
| Work with files shown in a Teams channel | SharePoint files | Teams presents the collaboration UI; SharePoint stores the files |
| Track one person's reminders or daily work | Microsoft To Do | Lists and tasks are user/mailbox-centered |
| Track shared work for a group or Team | Planner | Plans, buckets, assignments, and tasks model team work |

If ownership is unclear, ask whether the result should survive an employee leaving and who should see it. Shared organizational content usually belongs in SharePoint or Planner; personal working content usually belongs in OneDrive or To Do.

## Identity and authorization

Microsoft Graph has two identity modes:

- **Application (app-only):** the application acts as itself. Prefer it for unattended, organization-owned automation when the endpoint and granted application permissions support the operation. App permissions can be tenant-wide, so target explicit user/site/team IDs and avoid broad discovery unless required.
- **Delegated:** the application acts on behalf of a signed-in user and cannot exceed that user's effective access. Use it for user-centered workflows and for this CLI's complete Microsoft To Do CRUD surface.

An OAuth permission only makes an operation eligible. The target resource's membership, sharing, ownership, licensing, and service-specific rules can still deny access. A `403` should lead to checking both the Graph permission and the target resource relationship—not automatically requesting broader tenant-wide permissions.

Use the profile whose identity matches the intended actor. Do not switch from delegated to app-only merely to bypass a user's lack of access.

## SharePoint: sites, drives, files, lists, and items

A **site** is the collaboration container. A site can hold:

- one or more **document libraries**, exposed by Graph as `drive` resources;
- folders and files inside a drive, exposed as `driveItem` resources;
- **lists**, which define columns and contain `listItem` records.

Choose the model by the content:

- Upload/download a Word document, PDF, spreadsheet, image, or arbitrary bytes with `microsoft sharepoint files ... --drive-id DRIVE_ID`.
- Read or edit a workbook that Graph can open with `microsoft excel ... --item-id ITEM_ID --drive-id DRIVE_ID` (or `--path PATH`). For SharePoint workbooks, pass the document-library drive ID. Workbook operations are delegated-only and operate on the remote workbook through Graph; path targets are resolved to drive-item IDs before the workbook call for consistent behavior across drives.
- Create/update a business record with `microsoft sharepoint items ... SITE_ID LIST_ID`.
- Do not upload a document as a list item just because document libraries also have list metadata internally. Use the file interface unless the task explicitly concerns columns/metadata exposed through a list.

The CLI needs a **drive ID** for file transfer and a **site ID plus list ID** for list items. A SharePoint browser URL is not any of those IDs. If only a URL or Team/channel is known, first resolve the corresponding Graph resource; the generic request escape hatch can cover discovery operations that do not yet have a typed command.

For an overwrite-sensitive workflow, retrieve or uniquely name the target before uploading. A path identifies the file within that drive only; the same path in OneDrive and SharePoint refers to different content.

## Teams and its SharePoint relationship

A **Team** provides membership and collaboration. A **channel** provides a conversation space inside that Team. Messages belong to the channel; files do not live in the message store.

- Standard channel files are folders in the Team-connected SharePoint site's document library.
- Private and shared channels can use their own SharePoint sites/drives with narrower membership.
- When exact channel file storage matters, resolve the channel's files folder and reuse the returned drive/folder identifiers rather than guessing from display names.

The current typed Teams surface is read-only. It can inspect team/channel metadata, team members, channel messages, and chats. Use SharePoint file commands for channel documents. Do not imply that reading a Team grants access to every connected SharePoint file; access checks still apply at the underlying resource.

## OneDrive versus SharePoint

Both expose files through Graph drives, but the ownership semantics differ:

- **OneDrive:** user-owned work area. `microsoft files` uses `--user-id` or `profile.user_id` and falls back to `/me` for delegated use.
- **SharePoint:** site-owned shared library. `microsoft sharepoint files` requires the library's `--drive-id` explicitly.

Moving a document between them is a byte transfer, not a metadata-preserving move: download from the source, validate the bytes/content, upload to the destination, validate again, then delete the source only if the user requested a move rather than a copy.

## Word documents: file transfer, not document editing

Microsoft Graph represents a Word `.docx` as a `driveItem` file stream. The CLI can transfer that stream, but it does not expose Word paragraphs, tables, formatting, comments, or tracked changes as typed commands. There is intentionally no `microsoft word` command group.

When an agent needs to change a Word document, use this explicit workflow:

1. Download the source with `microsoft files download` or `microsoft sharepoint files download`.
2. Edit the local `.docx` with an external library or program chosen for the required fidelity.
3. Validate the generated file and retain a backup/version when the source matters.
4. Upload the complete replacement with the matching file command.
5. Re-download and validate when correctness matters.

Uploading is a whole-file replacement. It can overwrite a newer remote version and an external library may discard unsupported OOXML features. The CLI does not merge Word edits or provide collaborative document semantics. Use unique paths, copies, or provider version history when concurrent changes are possible.

The same download/edit/upload pattern applies to Excel features not represented by `microsoft excel`, including unsupported workbook formats or advanced objects. Create a new workbook with the local `excel workbook create` command (or another library), upload it as a normal drive item, and then use `microsoft excel` for supported remote operations.

## Outlook resources

Mail messages, events, and contacts belong to a user's Exchange mailbox. The `--user-id` selects that mailbox; it is not merely an audit label.

- Creating a message creates a draft. Sending mail is a separate side effect.
- Calendar events represent scheduled time and require meaningful time-zone-aware start/end values.
- Contacts are mailbox address-book entries, not Entra directory users.

For sends or calendar mutations, restate the recipient/time/subject before execution when ambiguity would affect another person. Use distinctive values in automated tests and remove disposable records afterward.

## To Do versus Planner

Use **To Do** for personal/user-centered tasks. A user owns task lists; each list contains tasks. This CLI requires a delegated profile for the complete create/update/delete workflow because Graph's application-permission support differs across To Do operations.

Use **Planner** for group-centered shared work. A plan is commonly associated with a Microsoft 365 group, a plan contains buckets, and tasks belong to a plan and bucket. Planner updates and deletes use optimistic concurrency: get the task, retain its current `@odata.etag`, and pass that ETag to the mutation. If it is stale, re-read and reconcile instead of forcing an overwrite.

Do not choose Planner solely because a task appears in Teams; decide whether it is shared plan work or one person's To Do item.

## IDs and discovery

Keep the resource type next to every saved identifier:

| Identifier | Selects |
| --- | --- |
| user ID / UPN | Exchange mailbox, OneDrive, chats, or To Do owner |
| Team ID | Team metadata, membership, and channel collection |
| channel ID | One channel inside a Team; use together with Team ID |
| site ID | SharePoint site |
| drive ID | One OneDrive or SharePoint document library |
| list ID | One SharePoint list; use together with site ID |
| plan ID | Planner plan |
| bucket ID | Planner bucket within a plan |
| task/list-item/message/event/contact ID | One resource within its owning service/context |

Prefer IDs returned by Graph or the provisioning/discovery workflow. Display names are for humans and can be duplicated or renamed.

## Cross-service workflow patterns

### Put a generated document where a Team collaborates

1. Identify the Team/channel and its actual SharePoint drive/folder.
2. Generate or retrieve the document locally.
3. Upload through SharePoint file commands using the resolved drive ID and intended path.
4. Download/read back when correctness matters.
5. Report the destination identifiers/path; do not claim a Teams message was posted unless that was a separate action.

### Turn a mailbox request into shared work

1. Read the relevant mail message from the intended mailbox.
2. Decide whether the follow-up is personal (To Do) or group-owned (Planner).
3. Create the task with a traceable title/link while avoiding unnecessary message-body copying.
4. Re-read the created task and report its ID and owning list/plan.

### Maintain a SharePoint tracker

1. Confirm the site, list, and required columns.
2. Search/list before creating when an external key should be unique.
3. Create or update fields as structured values.
4. Re-read the item to verify the stored fields.
5. Delete only disposable/test rows or when explicitly requested.

## Current CLI boundaries

- Teams operations are read-only.
- SharePoint file transfer requires a known drive ID; typed site/channel-to-drive discovery is not yet present.
- Planner typed coverage reads plans/buckets and manages tasks; it does not create plans or buckets.
- The generic Graph request command can reach other endpoints, but writes require `--allow-write` and remain real external side effects.

Authoritative background: [Graph permission types](https://learn.microsoft.com/en-us/graph/permissions-overview), [Excel workbook resources](https://learn.microsoft.com/en-us/graph/api/resources/excel?view=graph-rest-1.0), [DriveItem file resources](https://learn.microsoft.com/en-us/graph/api/resources/driveitem?view=graph-rest-1.0), [Teams channel storage](https://learn.microsoft.com/en-us/microsoftteams/standard-channels), [SharePoint list items](https://learn.microsoft.com/en-us/graph/api/resources/listitem?view=graph-rest-1.0), [To Do concepts](https://learn.microsoft.com/en-us/graph/todo-concept-overview), and [Planner concepts](https://learn.microsoft.com/en-us/graph/api/resources/planner-overview?view=graph-rest-1.0).
