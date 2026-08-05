# Expose allowlisted Platform Oversight Data without Organization access

Status: Accepted
Date: 2026-07-30
Origin: AF-237

Platform Administrators may read explicitly allowlisted cross-Organization oversight projections for users, Organizations, Memberships, Agents, bounded activity statistics, and model usage while remaining in Platform View. These projections do not establish an Active Organization, reuse Organization-scoped endpoints, or grant authority over Organization-owned resources; normal Organization View still requires a real Membership, and future impersonation remains the mechanism for exceptional tenant-scoped action.

## Considered alternatives

Prohibiting all visibility into Organization-owned facts would preserve the narrowest tenant boundary but prevent platform governance and operational oversight. Reusing Organization View with an implicit read-only role would expose a broad and growing resource surface, recreate synthetic cross-tenant authority, and make field-level privacy difficult to audit.

## Consequences

- Platform APIs use dedicated read models and repository queries with explicit field allowlists.
- Oversight may include Organization and user details, Membership relationships and counts, Agent identity and lifecycle metadata, bounded activity statistics, model-usage aggregates, and platform-borne cost data. Cost is classified as Platform Oversight Data because the Platform bears the model-provider expense even though attribution follows Organization-owned Agents.
- Oversight excludes conversation and message contents, tool inputs and results, logs, prompts, templates, Skills, configuration payloads, credentials, Secrets, and raw telemetry.
- Platform detail pages and drill-downs remain under Platform View URLs and authorization.
- Platform View provides one unified, filterable Security Audit Record page for safely mapped Platform- and Organization-scoped security events; resource detail pages may link to pre-filtered audit results instead of embedding separate histories.
- The Organization selector remains Membership-based for every user, including Platform Administrators; Platform Privilege never adds all platform Organizations to Organization View navigation.
- Adding a new oversight field is an authorization and data-classification decision, not an automatic consequence of adding it to an Organization-scoped DTO.
