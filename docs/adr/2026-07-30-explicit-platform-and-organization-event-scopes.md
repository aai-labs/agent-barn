# Give Domain Events explicit Platform and Organization scopes

Status: Accepted
Date: 2026-07-30
Origin: AF-237

Agent Farm will represent every Domain Event with an explicit Platform or Organization scope. Organization-scoped events require exactly one Organization identity, while Platform-scoped events prohibit one; this lets Platform Privilege changes enter the same transactional outbox and Security Audit Record projection pipeline as Organization security actions without inventing a synthetic “platform Organization.”

## Considered alternatives

Writing Security Audit Records directly would avoid changing the event envelope, but would create a second persistence path and lose the established atomic business-state-plus-event contract. Associating platform actions with a designated Organization would preserve the current schema but contradict the removal of default and synthetic Organizations.

## Consequences

- Event persistence and validation must allow a nullable Organization identity constrained by Event Scope.
- Platform-level event subjects may be Users.
- Existing Organization-scoped event contracts remain Organization-scoped.
- Platform Privilege grants and revocations and Organization suspension and reactivation are persisted atomically with their Domain Events and projected into Security Audit Records.
