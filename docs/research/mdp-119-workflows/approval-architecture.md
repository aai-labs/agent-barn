# Workflow approval architecture proposal

Status: Recommended candidate; requires a runtime/enforcement spike.
Recorded: 2026-10-13. Product contract: [product design](product-design.md).
Repository evidence and external sources: [runtime research](runtime-research.md).

## Primary recommendation

Agent Barn should own protected external writes. The Agent reasons and proposes a
typed action; a trusted controller persists the proposal, obtains a human
decision, executes the exact authorized payload through a trusted adapter, and
records the result. Workflows use an execution context whose capabilities cannot
bypass that boundary. A prompt asking the Agent to wait is not enforcement.

Start with a small set of explicit operations. A generic HTTP/shell adapter would
make both authorization and a nontechnical approval preview difficult to judge.
Ordinary interactive Agent capabilities are not automatically governed by this
proposal. Their credentials, native transport, shell, network, and automatic
delivery paths must be considered before claiming workflow isolation.

Use PostgreSQL for business state and the current worker infrastructure as a
candidate transport. Queue messages wake workers; stored state controls which
transitions they may perform. Existing Domain Events provide transaction seams
and delivery patterns, not a universal exactly-once external-effect guarantee.

## Continuation alternatives

The preferred spike candidate preserves tool-call semantics: a protected tool
creates a proposal and yields instead of performing the effect. The current turn
ends after its transcript and checkpoint are durably saved. Following the human
decision, a new turn receives the original tool call's result, either the recorded
provider outcome or a structured denial with guidance.

This requires runtime support for capturing context, ending the turn cleanly,
matching tool-call IDs, and restoring the next turn without reexecuting earlier
effects. It is not demonstrated for either pinned runtime. Transcript persistence
alone does not preserve sandbox files, subprocesses, or framework-local state.

If exact tool-result continuation is unavailable, evaluate a fresh reasoning turn
with an explicit handoff: current step, relevant transcript/summary, completed
actions, preserved outputs, the pending proposal and its decision. Measure
context loss and duplicate proposals against an uninterrupted baseline.

Native tool interception with durable suspended-call recovery is an alternative,
but the controller must remain the authorization/execution boundary. A live
blocked process is not durable storage. Engine selection (bounded custom
controller, DBOS, Temporal, or another candidate) follows this evidence.

## Proposed state and identities

| Record | Purpose |
| --- | --- |
| Workflow / version | Agent and Organization ownership, ordered definition, input contract, per-step/final artifact requests, immutable saved version |
| Run | Pinned version and inputs, initiating actor, execution authority, lifecycle/generation, current step |
| Step execution / attempt | Durable context, runtime/configuration identity, current work item, result/error, lease generation |
| Action proposal | Random request ID, run/step/attempt linkage, adapter/version, canonical payload, target/account identity, artifact hashes, preconditions, expiry and predecessor |
| Decision | Proposal identity/hash, actor, verdict, guidance, timestamp and observed proposal/run generation |
| External effect / attempt | Stable logical operation identity, dispatch generation/lease, intent, receipt, outcome and reconciliation history |
| Artifact | Run and source step, immutable object/version identity, actual filename/media type/size/checksum, preservation/readiness state |

These are research entities, not approved table names or migrations. Scope every
relationship to the same Organization and Agent. Pending proposals, decided
proposals, effect dispatch, and completed steps are distinct states.

## Decision and execution invariants to prove

- Build the approval preview deterministically from the stored payload using
  adapter code. Keep the Agent's explanation separate from authoritative facts.
- Bind authorization to the exact operation, target/account, parameters, adapter
  version, and artifact bytes/version. Changes require another proposal.
- Atomically accept one decision per proposal. Duplicate identical decisions are
  idempotent; conflicting or stale decisions return the existing outcome or a
  conflict. UI and Chat call the same service.
- Recheck applicable permissions, cancellation intent, expiry, credential
  binding, and target preconditions at the dispatch boundary. Do not silently
  substitute a different account or reinterpret changed payloads.
- Record refusal before continuing. Deliver the refused action and verbatim user
  guidance as structured context. Guidance is not authorization.
- Detect identical re-proposals after refusal and bound repeated requests.
  Completion criteria, permitted skips, and escalation policy must be explicit.
- Commit effect intent and safe business events inside a repository-owned
  transaction; make network/model calls outside the transaction.
- Accept completion only from the current attempt/generation. Reconcile missed
  wakeups and expired claims from durable state.

The exact cancellation linearization point remains a decision. A committed
cancel cannot unsend a request already dispatched; disclose in-flight/uncertain
actions and record their eventual outcomes. A lease fence protects database
updates but cannot recall an external request from an old worker.

## Approval once versus external effects

One accepted human decision is achievable. Exactly-once behavior across arbitrary
providers is not established by a local outbox or an approval ID.

Classify each adapter's retry contract: provider-supported idempotency, reliable
reconciliation by client reference, or neither. Keep one stable logical key
across attempts; an attempt number must not silently become a new effect key.
Account for provider deduplication windows and eventually consistent reads.

An uncertain post-dispatch timeout becomes `UNKNOWN` and blocks dependent work
until reconciled. Do not mark it failed and retry blindly. If a human elects to
try again despite uncertainty, disclose the duplicate risk and explicitly define
the new operation/approval. Compensation is another authorized action, not
automatic rollback.

## Authority and capability isolation

The proposed dedicated workflow principal acts on behalf of identified users;
the permissible scope still needs a decision. Establish initiator/approver
authority, handling of removed Memberships and changed Agent Access, and the
effect of Organization suspension or Agent stop/delete before implementation.
Do not treat product-triggered work as the RBAC brief's narrow operator/schedule
exception.

The existing optional integration-isolation feature is useful context, not proof
of action approval: direct modes still materialize credentials, proxy modes
forward requests, and token-broker modes may issue access tokens used to call
providers directly. Prove the complete workflow capability boundary, including
vetted reads, egress, shell, filesystem-held credentials, native message tools,
and implicit final-result delivery. Credential storage isolation and exact-action
authorization are separate contracts.

## Artifacts

The written artifact description becomes an instruction to the relevant step.
Runtime tooling generates the bytes; a manifest alone is not proof of success.
The controller validates and preserves actual files, then records scoped
metadata and object/version identity. Storage service, supported generator/preview
capabilities, size limits, content handling, and retention remain unselected.

Preserved outputs should be immutable snapshots. An action involving an artifact
must reference the exact approved version. Validate source-path ownership and
upload capability; arbitrary Agent-provided paths or URLs must not select another
Agent's files. Serve previews/downloads through authorized product reads. Event
envelopes contain safe identities and status, not prompts, credentials, file
bytes, or provider payloads.

## Second opinion and disagreements

Opus 5.5 reviewed a generic design-only brief, without repository access. It agreed
with controller-owned writes and suggested continuing through the saved tool
result where supported. Its strongest additions were adapter-owned previews,
read/egress bypass checks, limits on repeated rejected proposals, and deliberate
human-comprehension testing.

The opinion is advisory, not validation. Its proposed thresholds and timeline
are not project commitments. Broad run-epoch invalidation, approval revocation
cutoff, dedicated-principal permission semantics, and guarantees around cancel
versus dispatch require a precise contract; they are not adopted merely because
the model recommended them.

## Validation spike

Prove one protected operation end to end in the pinned runtime, then repeat for
the other supported runtime before claiming parity:

1. Propose an action and preserve a step artifact; verify no external write yet.
2. Restart the worker/runtime while the request awaits a decision.
3. Decline with guidance; restore context and obtain a different proposal.
4. Confirm it remains unexecuted until a fresh decision.
5. Approve through Chat and observe the same outcome in the workflow view.
6. Execute via the adapter, record a receipt, continue the step, and preserve the
   requested final artifact.

Also test bypass attempts, duplicate/out-of-order results, concurrent decisions,
stale artifact/payload/account changes, access revocation, expiry, cancellation
before/after dispatch, provider timeout after acceptance, and stale workers.
Use controlled providers to exercise both idempotent and non-reconcilable writes;
use a real pinned runtime to establish continuation and policy behavior.

Agree performance and comprehension thresholds before measurement. No-go if
protected effects can bypass enforcement, durable context cannot be restored
adequately, or reviewers cannot understand the preview. A proposal-only mock
cannot satisfy these gates. Defer broad adapter coverage, advance authorization
policies, cross-Agent workflows, and large-scale fanout until this loop works.

Implementation checks must follow [testing guidance](../../guidelines/testing.md):
migrated PostgreSQL coverage, pinned-image contracts, and browser behavior at the
relevant boundaries. No workflow spike or application test result is claimed by
this research package.
