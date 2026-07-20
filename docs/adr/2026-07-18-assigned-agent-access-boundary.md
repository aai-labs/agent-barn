# Use assigned Agent access as the resource boundary

Status: Accepted
Date: 2026-07-18
Origin: [Agent farm multi-organization support](https://aai-labs.atlassian.net/wiki/x/MIA0pQ)

Agents remain Organization-owned, but ordinary Members can see and act only on Agents assigned to their Membership. A distinct Agent Access relationship supplies that assignment, while the Agent Creator remains immutable provenance; this keeps resource visibility separate from Organization Role permissions and avoids treating creation as ownership.

## Considered alternatives

- Let Members see every Agent but manage only assigned Agents. This violates the feature's assigned-only visibility contract.
- Infer access from the creator field alone. This cannot represent collaboration or explicit grants.
- Add viewer/operator/manager access levels now. Organization Role permissions already determine allowed actions, so multiple grant levels add overlapping policy and UI scope.

## Consequences

Agent creation establishes access for its creator. Owner/Admin may grant or revoke access to any Agent; a Member may grant or revoke access only for an Agent they created, and recipients cannot propagate access. Creators and recipients otherwise receive the same assigned-Agent capabilities from their Organization Role. Transfer and creator self-revocation are outside the initial Agent Access feature.

Agent Access scopes the full Agent aggregate, including conversations, tool calls, costs, skills, configuration, and Agent Secrets; individual permissions still determine allowed operations, and secret plaintext is never returned. Visibility predicates must be applied in persistence queries before counting and pagination. Inaccessible Agents and subordinate resources return 404, while a visible resource lacking an action permission returns 403. API responses expose effective actions for UI rendering, but mutations always reauthorize server-side.

Existing Agents have no recoverable creator. Migration therefore grants every existing accepted Membership access to every existing Agent in its Organization, excludes pending invitees, and records legacy creator provenance as unknown; new Agents use assigned-only visibility.
