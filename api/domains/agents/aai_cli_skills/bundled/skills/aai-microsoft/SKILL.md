---
name: aai-microsoft
description: Work with Microsoft 365 through aai-cli by choosing the right Microsoft service and resource model, then using durable Graph credentials for Outlook, OneDrive, SharePoint, Teams, Excel, To Do, and Planner workflows.
---

# aai-cli Microsoft Graph

Use this skill for Microsoft 365 work through `aai-cli microsoft`. Start from the user's intent and Microsoft 365 ownership model, not from the command list. Read the concepts reference before a cross-service or file-editing workflow.

## Choose the service first

- **Outlook / Exchange** owns a user's mail, calendar, and contacts. Use it for communication and scheduling tied to a mailbox.
- **OneDrive** is a user's personal work-file area. Use it for files owned or staged by one user, even when those files may later be shared.
- **SharePoint** is the shared content layer. A site contains document libraries (`drive` resources) for files and lists for structured rows/columns. Use document-library file commands for shared documents; use list-item commands for records such as requests, assets, or statuses.
- **Teams** is the collaboration/conversation layer over teams and channels. Read channel messages and membership there, but treat channel files as SharePoint content. A standard channel uses the team's SharePoint site; private and shared channels can use separate sites.
- **Microsoft To Do** is user-centered personal task management. Use it when the task belongs in one user's lists and daily workflow.
- **Planner** is shared plan/task management, commonly attached to a Microsoft 365 group or Team. A plan contains buckets, and buckets organize tasks.
- **Microsoft Graph** is the common API surface across these products. Use `microsoft request` only when the needed Graph operation lacks a typed command.

## Excel and Word are different kinds of files

- **Excel workbooks:** `microsoft excel` calls the documented Graph workbook API for worksheets, ranges, tables, and table rows. It requires a delegated profile with `Files.ReadWrite` access; application profiles are rejected because Graph does not support application permissions for workbook operations. For SharePoint workbooks, pass the document-library `--drive-id`.
- **Word documents:** Graph exposes `.docx` files as `driveItem` content, not as paragraphs or tables. There is no `microsoft word` editor in this CLI. Download the file with `microsoft files` or `microsoft sharepoint files`, edit it with an external library/program, then upload the complete replacement. Consider a backup, version history, concurrent edits, and features the external library may not preserve.
- **Teams files:** channel files are SharePoint files, so use the SharePoint file workflow rather than treating them as Teams messages.

Read [Microsoft 365 concepts and routing](references/microsoft-365-concepts.md) before acting when the request crosses products, refers to a Team or SharePoint URL rather than IDs, or leaves ownership/visibility ambiguous. It explains resource relationships, identifier choice, auth choice, and common workflows.

Confirm the active profile or pass `--profile`. App-only profiles are best for unattended organization-owned automation. Delegated profiles act on behalf of one user and are required by this CLI for complete Microsoft To Do CRUD. Both obtain short-lived access tokens automatically from credentials saved in the encrypted secret store; never request or copy an access token into a command.

Prefer typed commands for supported operations. Use `microsoft request` only for a Graph endpoint without a typed command. Writes through `request` require `--allow-write`.

Most user resources accept `--user-id`; otherwise they use `profile.user_id`. IDs belong to different resource types and are not interchangeable: a Team/group ID is not a site, drive, list, channel, plan, or bucket ID. SharePoint list commands require site and list IDs. Use `microsoft files` for OneDrive and the explicit `microsoft sharepoint files` commands with `--drive-id` for a SharePoint document library. Use `microsoft excel` with `--item-id` or `--path` for workbook operations. Planner task update/delete require the current `@odata.etag` from a preceding get/create/update response.

Treat creates, sends, updates, and deletes as external side effects. Read the target first when practical, use stable identifiers, and report what changed. Supply request bodies through `--json PATH` or `--json -` for complex or sensitive values rather than shell-inline JSON.

List commands aggregate Graph pages up to `--limit` and return the provider's `value` array. Successful output is JSON on stdout; errors are structured JSON on stderr. Downloaded file bytes go only to `--output`.

See [the command reference](references/command-reference.md) only after choosing the service/resource. It contains exact command shapes, bodies, and mutation mechanics.
