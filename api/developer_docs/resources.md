# Organizations, Templates, Skills, and credentials

The Organization ID appears in `/api/v1/auth/context`. Organization routes use `/api/v1/organizations/{organization_id}`. An authenticated user can create an Organization with `POST /api/v1/organizations`; `GET`, `PATCH`, and `DELETE` at the Organization path use current Organization permissions. Membership endpoints beneath `/members` support listing, invitations, role changes, removal, ownership transfer, and resending invitations.

Templates and Skills live beneath `/organizations/{organization_id}/templates` and `/skills`. Read operations are available according to Organization permissions. Owners and Admins can manage shared definitions. Agents pin Template Versions; changes to a shared Template do not silently update a running Agent.

Shared Credentials live beneath `/organizations/{organization_id}/shared-credentials`; credentials are never returned as plaintext. Agent-specific Secrets and integration configuration are controlled by Agent Permissions. Account-level Slack configuration tokens use `/auth/me/slack-config-token`. Google authorization and token exchange use `/integrations/google/...`; callback navigation remains a browser/provider flow.

For exact field names and request bodies, consult [OpenAPI](/api/v1/openapi.json). In particular, the API field `agent_type` names the Agent Runtime (Hermes or OpenClaw).
