# Use explicit organization context for tenant-scoped work

Status: Accepted (retrospective)
Date: 2026-07-17
Origin: AF-147

Multi-organization navigation needs a bookmarkable active organization while API authorization needs one consistent tenant context across domain endpoints. Agent Farm places the organization ID in organization-scoped dashboard URLs and sends it as `X-Organization-Id` on API requests; the backend validates membership, falls back to the default organization when the header is absent, and synthesizes transient owner-level organization context for superusers rather than persisting artificial memberships.

## Consequences

- Organization-scoped UI routes and the request header must remain synchronized.
- Global account and administration routes remain outside the organization URL prefix.
- Every tenant-scoped API path must resolve and enforce organization context consistently.
- Organization-scoped query caches must include organization identity or be removed safely when the active organization changes.
- Superuser access is represented in request context without creating membership rows.

Current behavior and source paths are documented in [`../features/identity-and-organizations.md`](../features/identity-and-organizations.md) and [`../architecture/ui.md`](../architecture/ui.md).
