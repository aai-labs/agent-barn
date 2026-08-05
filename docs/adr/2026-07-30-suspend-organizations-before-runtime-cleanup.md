# Enforce Organization suspension before asynchronous runtime cleanup

Status: Accepted
Date: 2026-07-30
Origin: AF-237

Organization suspension takes effect atomically before runtime cleanup: the business transaction marks the Organization Suspended, records its reason, and stages the suspension Domain Event. Organization-scoped product access, Agent starts, runtime Ingest, webhooks, and background work reject the Suspended Organization immediately, while an idempotent Event Handler stops its running Agent resources asynchronously and retries cleanup failures.

## Considered alternatives

Stopping every Agent before committing suspension would make the endpoint synchronous but would leave tenant access enabled whenever Kubernetes cleanup is slow or unavailable. Treating cleanup failure as suspension failure would couple a security boundary to external runtime availability.

## Consequences

- A Suspended Organization can temporarily have runtime resources still undergoing cleanup without regaining product or Ingest access.
- Suspension cleanup is tracked as Pending, Running, Complete, or Failed. Platform Oversight Data reports that state and failure counts without exposing runtime logs.
- Reactivation is rejected until cleanup is Complete; Failed cleanup remains retryable while the Organization stays Suspended.
- Reactivation never restarts Agents automatically.
- Runtime cleanup must be idempotent and recoverable through Event Delivery reconciliation.
