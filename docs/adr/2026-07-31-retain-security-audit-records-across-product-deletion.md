# Retain Security Audit Records across product deletion

Status: Accepted
Date: 2026-07-31
Origin: AF-237

Security Audit Records are immutable compliance artifacts retained independently of the mutable product resources they describe. Organization, User, Membership, Agent, and other subject deletion must not cascade into audit history; records retain typed identities and bounded display snapshots so historical actions remain intelligible and searchable after their live references disappear.

## Considered alternatives

Using Domain Event Outbox Messages directly as the audit store would avoid another projection but would couple compliance retention and query shape to transport records, including their current Organization foreign-key lifecycle. Cascading audit deletion with product data would simplify referential integrity but allow ordinary administration to erase security history.

## Consequences

- Security Audit Records do not require live foreign-key references to actors or subjects.
- Deleted actors and subjects remain visible as historical snapshots and are marked deleted when that state is known.
- The unified Platform Audit page reads Security Audit Records, not Outbox Messages or Event Deliveries.
- Records are retained indefinitely until an explicit, separately approved retention policy replaces this default.
