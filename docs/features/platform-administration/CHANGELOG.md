# Platform administration — change log

Status: Active
Epic: [AF-235](https://aai-labs.atlassian.net/browse/AF-235)
Related context: [Identity and Organizations](../identity-and-organizations.md), [Domain Events](../domain-events.md), [Platform oversight boundary ADR](../../adr/2026-07-30-platform-oversight-without-organization-access.md)

## Current state

- Delivered: AF-237 self-service Organization creation, invitation-based Platform user onboarding, per-creator limits, membership-only Organization selection, bounded Platform Privilege administration, explicit Platform/Organization event scopes, and durable Security Audit Record projection.
- Delivered: Platform View now includes allowlisted Organization and user identity detail, Organization membership drill-downs, and dedicated read contracts that exclude tenant configuration.
- In transition: broader Platform Oversight detail/statistics surfaces—Agents, activity, model usage, costs, suspension, and unified audit exploration—remain deferred under the AF-235 backlog.
- Next: Organization suspension/reactivation, unified audit exploration, and platform oversight details/statistics are captured in `../../plans/AF-235-remaining-platform-management-tasks.md`.
- Blockers: none for the delivered AF-237 slice.

## Changes

### 2026-07-31 — AF-237 — one implementation PR

- Delivered: any authenticated user can create an Organization and becomes its immutable Creator and initial Owner; Platform Administrators use the same path and quota.
- Changed: replaced password-setting Platform user creation with invitation-based onboarding that atomically creates the pending User, initial Organization, Owner Membership, and set-password token; platform password reset and account deletion remain removed.
- Changed: kept Organization Name as a non-unique display label; Platform View uses creator identity and Organization ID for disambiguation instead of overloading names as identifiers.
- Changed: removed platform Organization provisioning; added reasoned Platform Privilege grant/revoke, user-session credential enforcement, scoped Domain Events, and deletion-independent Security Audit Records.
- Changed: updated the Organization switcher and Platform users/Organizations pages so the authority and membership boundaries are visible in the UI.
- Added: Platform Organization and user detail pages expose only the allowlisted identity and membership projections supported by the Platform oversight boundary; tenant configuration remains outside these contracts.
- Follow-up: implement the three deferred AF-235 tasks without expanding Platform Administrators into tenant membership or impersonation.
