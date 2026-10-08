# Supported product API

## Contract

The Product API at `/api/v1` is the supported v1 HTTP contract. Its complete OpenAPI schema is at `/api/v1/openapi.json`; `/api/v1/docs` is the interactive reference. `/api/v1/discovery` lists registered operations, and `/api/v1/developer` serves task guides in HTML and Markdown. `/api/v1/llms.txt` points agents to the relevant guides and schema. The web app forwards root `/llms.txt` and `/llms-full.txt` to the API.

All existing user-authenticated product routes accept a Personal API Key using `Authorization: Bearer abk_...`. The same business permissions apply to sessions and keys. Protocol-specific endpoints retain their own credentials: login and password/reset workflows, Google callbacks, Teams webhooks, and runtime Ingest.

Personal API Keys are User-owned and valid across the User's current Organization Memberships. Platform Administrator privilege also applies when current. Read-only keys may make read requests; full-access keys may make writes, including issuance and revocation of the User's keys. The Google authorization URL is classified as a write because it starts a credential grant. API Key creation defaults to read-only with no expiration, and the complete secret is displayed only once. Password changes and resets invalidate keys through the User security stamp. Revocation takes effect on the next request.

The key table stores a SHA-256 hash, display prefix, owner, name, mode, issue-time stamp, optional expiry, revocation, and last use. Account-security creation and revocation events commit atomically with the key mutation and are projected to Security Audit Records. Key material never enters events or response metadata other than the one-time creation response.

## Authorization boundaries

Organization-scoped URLs require a real current Membership. Agent and subordinate-resource visibility uses the existing repository-level Agent Access checks. Platform routes require current Platform Administrator privilege. Invalid keys return 401, read-only mutation attempts return 403, and existing tenant concealment remains 404. Key management is owner-scoped.

## Source map and change impact

Authentication and management: `../../api/domains/api_keys/`, `../../api/domains/auth/utils.py`. Discovery and public guides: `../../api/domains/discovery/`, `../../api/developer_docs/`. Account UI: `../../ui/src/features/account/`. Security events: `../../api/domains/events/`.

Changes to any user-authenticated route must preserve session and key access and accurately update OpenAPI and developer guides. Changes to Agent/subordinate resource access must follow the RBAC implementation brief. Incompatible v1 wire changes require a new major API version.

The checked-in `api/developer_docs/operations-v1.json` records current method, path, and operation ID pairs. The API contract test detects accidental operation removal or renaming; reviewers update it intentionally for additions. Schema shape and behavioral compatibility still require API review and integration tests.

The provider-session reconnect operation remains in the v1 inventory and discovery for compatibility, with OpenAPI `deprecated: true`. Authorized active-Connection requests receive terminal `409` and Agent restart guidance; existing authentication, permission, and tenant-concealment responses remain unchanged. See the [developer resource guide](../../api/developer_docs/resources.md).
