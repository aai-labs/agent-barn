# Separate Organization Roles from Agent Access Roles

Status: Accepted
Date: 2026-07-21
Origin: [AF-150](https://aai-labs.atlassian.net/browse/AF-150)

Agent Farm uses two role families because organization governance and authority over one Agent answer different questions. Every Membership has one fixed Organization Role—Owner, Admin, or Member—while each explicit Agent Access relationship carries one Agent Access Role whose permissions govern that Agent aggregate. Organization Role permissions do not grant assigned-Agent operations.

Every Organization can use the locked Agent Access Roles Viewer, Editor, and Owner. Viewer grants read, activity, and cost access; Editor adds configuration, lifecycle, Skill assignment, and credential management; Owner adds deletion and access management. Organization-defined custom Agent Access Roles are handled separately under AF-216.

Organization Owner/Admin and superuser in explicit Organization context have implicit Agent Owner authority for every Agent. Agent creation records immutable creator provenance and grants the creator explicit Agent Owner access, so later Organization Role changes do not erase that assignment. Any explicit role with access-management permission can grant, change, or revoke access onward; creator provenance is not a separate authorization source.

## Considered alternatives

- Derive Agent actions from the Membership's Organization Role and use Agent Access only as a visibility flag. This cannot express Viewer, Editor, or Owner authority independently for each Agent and couples organization governance to resource collaboration.
- Put an access level directly on Agent Access. Fixed levels are simpler, but organization-defined Agent roles require a permission-backed role relationship rather than a closed enum.
- Materialize Owner access for every Organization Owner/Admin and Agent. Implicit authority avoids quadratic rows and makes Organization Role changes effective immediately; explicit creator access still preserves the creator's Agent authority after demotion.

## Consequences

Agent authorization resolves an effective Agent Access Role: implicit Owner for Organization Owner/Admin or superuser in explicit Organization context, otherwise the explicit role carried by Agent Access. The role's permissions are narrowed by Agent lifecycle state. Repositories apply visibility before counting and pagination; inaccessible and cross-Organization resources return 404, while visible resources lacking an operation return 403.

Existing accepted Organization Members receive Editor access to existing Agents during migration so visibility is preserved; known creators receive Owner. Pending and removed Memberships receive no access. New Agents grant explicit Owner access only to their creator.

The platform Permission catalogue remains shared, but Organization Role permissions govern organization capabilities and Agent Access Role permissions govern one Agent aggregate. Tokens do not embed grants; current database state is resolved on each request. Agent access-management UI is deferred to AF-217, and event/audit infrastructure remains deferred to AF-218 through AF-221.
