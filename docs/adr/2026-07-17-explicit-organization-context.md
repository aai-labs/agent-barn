# Use explicit organization context for tenant-scoped work

Status: Accepted (retrospective)
Date: 2026-07-17
Origin: AF-147

Multi-organization navigation needs a bookmarkable active organization while API authorization needs one consistent tenant context across domain endpoints. Agent Farm places the organization ID in organization-scoped dashboard URLs and organization-scoped API URLs; the backend validates membership from the `organization_id` path parameter and synthesizes transient owner-level organization context for Platform Administrators rather than persisting artificial memberships. Platform View and platform routes have no active Organization. The earlier default-organization fallback has been removed.

## Consequences

- Organization-scoped UI routes and API routes must carry the same organization identity in the URL.
- Account routes and platform administration routes remain outside the organization URL prefix.
- Every tenant-scoped API path must resolve and enforce organization context consistently.
- Organization-scoped query caches must include organization identity or be removed safely when the active organization changes.
- Superuser access is represented in request context without creating membership rows.

Current behavior and source paths are documented in [`../features/identity-and-organizations.md`](../features/identity-and-organizations.md) and [`../architecture/ui.md`](../architecture/ui.md).
