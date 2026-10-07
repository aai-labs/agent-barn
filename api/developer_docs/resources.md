# Organizations, Templates, Skills, and credentials

The Organization ID appears in `/api/v1/auth/context`. Organization routes use `/api/v1/organizations/{organization_id}`. An authenticated user can create an Organization with `POST /api/v1/organizations`; `GET`, `PATCH`, and `DELETE` at the Organization path use current Organization permissions. Membership endpoints beneath `/members` support listing, invitations, role changes, removal, ownership transfer, and resending invitations.

Templates and Skills live beneath `/organizations/{organization_id}/templates` and `/skills`. Read operations are available according to Organization permissions. Owners and Admins can manage shared definitions. Agents pin Template Versions; changes to a shared Template do not silently update a running Agent.

Shared Credentials live beneath `/organizations/{organization_id}/shared-credentials`; credentials are never returned as plaintext. Agent-specific Secrets and integration configuration are controlled by Agent Permissions. Google authorization and token exchange use `/integrations/google/...`; callback navigation remains a browser/provider flow. Communications Connections are managed beneath each Agent's `/connections` routes.

For exact field names and request bodies, consult [OpenAPI](/api/v1/openapi.json). In particular, the API field `agent_type` names the Agent Runtime (Hermes or OpenClaw).

The deprecated `POST /api/v1/organizations/{organization_id}/agents/{agent_id}/connections/{connection_id}/reconnect` route remains for compatibility and discovery. Authorized requests for an active Connection always return `409`; native transport recovery requires restarting the Agent. Authentication, Agent update permission, and tenant visibility checks still apply, so invalid credentials, insufficient permission, and concealed or missing resources retain their `401`, `403`, and `404` responses. The route creates no reconnect work.
