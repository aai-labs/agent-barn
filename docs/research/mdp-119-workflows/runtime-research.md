# Runtime research and current boundaries

Status: Evidence for evaluation; no runtime integration selected.
Checked: 2026-10-13. Repository baseline: `d3e7b8e4`.
Related: [approval proposal](approval-architecture.md).

## Existing Agent Barn contracts

| Surface | Owning source | Consequence for this proposal |
| --- | --- | --- |
| Organization and accessible-Agent scoping | [RBAC brief](../../features/rbac/IMPLEMENTATION-BRIEF.md) | Filter subordinate reads/counts/pagination in repositories; reauthorize mutations; resolve workflow execution authority explicitly |
| Native versus gateway-owned chat | [Runtime/deployment](../../architecture/runtime-and-deployment.md), [Communications](../../features/communications/CHANGELOG.md) | Native Slack/Discord/Telegram/Teams approval interactions cannot be assumed to pass through the shared gateway |
| Command approvals | [Interactive approvals](../../features/interactive-approvals/CHANGELOG.md) | Web Chat retains approval identities; runtime command decisions are not a persistent workflow business-approval ledger |
| Trigger admission | [Agent Webhooks](../../features/agent-webhooks.md) | Submission acceptance is not execution completion; workflow result/continuation requires another contract |
| Event transactions and workers | [Domain Events](../../features/domain-events.md) | Reuse transaction seams and at-least-once delivery patterns; keep sensitive workflow content outside event envelopes |
| Provider capabilities and credentials | [Integrations](../../features/integrations.md#optional-credential-isolation), [credential-gateway delivery](../../features/credential-gateway/CHANGELOG.md) | Direct/proxy/token-broker routes must be considered independently when proving protected-write enforcement |
| Existing Agent UI | [UI architecture](../../architecture/ui.md), [web app conventions](../../guidelines/webapp.md) | Preserve Agent-centered routes and controls; define schemas, queries, cache scoping, and mutations when implemented |

At this baseline [Hermes](../../../hermes-base/Dockerfile) pins
`nousresearch/hermes-agent:v2026.8.19` and
[OpenClaw](../../../openclaw-base/Dockerfile) installs `openclaw@2026.8.2`.
Image tests and source inspection of these exact versions must establish support;
upstream documentation below does not establish deployed parity.

The runtime guide maps command-approval mode only for Hermes. Its pinned
unattended cron/heartbeat policy denies dangerous-command gates immediately;
it does not provide a human-waiting workflow checkpoint. Current OpenClaw
configuration has no user-configurable command-approval parity through that same
field. Neither fact changes through this documentation branch.

## Hermes Kanban

Upstream Kanban persists tasks, dependencies, comments, attempts, and events in
per-board SQLite. Dispatchers claim runnable work and spawn workers; blocking
closes an attempt, and unblocking allows a new worker to read retained task
context. It is durable task-level handoff, not an instruction-by-instruction
process snapshot. Declared completion/review artifacts are preserved before
scratch-workspace cleanup. Kanban is single-host and local PID-based recovery is
not a distributed scheduler. [Official Kanban reference](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban).

Same-card review uses `kanban_request_review`; reviewers complete, request changes,
or block for external input. Human-only review can disable automatic reviewer
dispatch. Run-ownership checks fence stale lifecycle calls, but the documentation
explicitly distinguishes cooperative scoping from OS confinement. [Worker-lane contract](https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban-worker-lanes).

Evaluation hypothesis: use the handoff/context pattern, or investigate a runtime
adapter around it. Task review accepts work as complete; it does not by itself
authorize an exact provider write before execution. Do not introduce a second
canonical business-run ledger inside a local board without an ownership contract.

## OpenClaw Workboard

Workboard is a bundled, optional Kanban-style plugin for one Gateway. It persists
cards and provides assignment, dependencies, comments, claim/heartbeat/release,
dispatch, artifacts, and links to native sessions. The Gateway starts subagent
workers and records lifecycle updates without an open browser. Session state
owns transcripts and execution; completed sessions move cards to review, failures
to blocked, and human acceptance can move them to done. [Official Workboard guide](https://docs.openclaw.ai/plugins/workboard).

Evaluation hypothesis: Workboard is the closest board counterpart to Hermes
Kanban, but is not automatically a runtime-neutral workflow controller or
exact-action authorization boundary. Check its availability and API in our pin.
OpenClaw operator scopes are not Agent Barn Membership/Agent Permissions.

## OpenClaw Lobster and native recovery

Lobster is an optional local pipeline runner with approval/input checkpoints.
It saves continuation JSON and returns a resume token without holding a live
process for a human. Tokens are not bound to a user/session. Its standard
`approve: false` path cancels/finalizes the pipeline, which differs from the
agreed decline-with-guidance/reconsideration UX. [Official Lobster guide](https://docs.openclaw.ai/tools/lobster).

Current native subagent recovery settles interrupted children and leaves the
parent to decide continuation; it is not blanket automatic relaunch of every
interrupted child. [Native subagent operations](https://docs.openclaw.ai/tools/subagents/operations).

Evaluation hypothesis: these provide useful execution primitives, but their
continuation, cancellation, feedback, and authorization semantics need explicit
adapter contracts and pinned-image evidence.

## TaskFlow: original dependency needs revisiting

The original ticket requested an OpenClaw TaskFlow visibility mirror and referred
to a Webhooks plugin integration. Current upstream release notes for
v2026.9.7 state that Tasks/TaskFlow panels, commands, APIs, and TaskFlow Webhooks
were removed while Workboard remains. [Release notes](https://docs.openclaw.ai/releases/2026.9.7).

The migration guide states there is no compatibility facade; retained historical
database rows do not restore the runtime API. [Removed surfaces and replacements](https://docs.openclaw.ai/plugins/sdk-migration/removed-surfaces).

Our OpenClaw pin predates that removal. Do not conflate current upstream status
with what the pinned image contains, or build against an older page without a
versioned upgrade strategy. Revisit the requirement before choosing a mirror or
runtime integration. No dependency change is proposed in this branch.

## Required evidence before an implementation plan

- Supported launch/result/context-handoff APIs in each pinned image.
- Actual behavior across blocked-worker, runtime, and Gateway restarts.
- Clean separation of workflow execution from existing Agent credentials,
  native delivery, workspace state, and ordinary interactive execution.
- Relationship between local task/card identities and authoritative product
  run/step/proposal identities, including stale updates and recovery.
- Artifact handoff proving actual bytes and safe access, not just a path/manifest.
- Current provider-specific idempotency/reconciliation guarantees for the chosen
  initial operation.

Keep consequential choices provisional until measured. Runtime upgrades, if
needed, must follow their existing image-contract and release guidance as a
separate requested change.
