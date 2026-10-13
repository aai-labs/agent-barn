# Workflow product design

Status: Product direction agreed in discussion; not implemented.
Recorded: 2026-10-13. Related context: [research entry point](README.md).

## Audience and ownership

Start with workflows belonging to one Agent. Organization-wide processes using
multiple Agents are desired later. The primary audience includes nontechnical
operators; the interface must not require YAML, source definitions, technical
step types, or a graph editor.

Use the existing Agent detail frame and a Workflows tab: Agent identity, status,
Configuration and Share controls, and the neighboring Chat/Conversations/Activity
surfaces remain recognizable. A waiting decision is visible from the Agent page,
not discoverable only inside a run. See the [prototype](prototype.html).

## Create, review, save, run

1. The user describes a repeatable outcome in ordinary language. Ready-made
   examples help them start; a workflow may also be edited after creation.
2. The Agent proposes an ordered, readable plan and a name. The user can edit,
   add, remove, or reorder steps. Generation proposes a plan; it does not publish
   or execute it without the user's save action.
3. Saving makes the workflow available on this Agent. Saving does not start a run.
4. Running is explicit. The user supplies any needed inputs and can inspect
   progress, step results, history, and preserved artifacts.

A run should retain the workflow version it started from. Editing the saved
workflow must not silently replace the definition or approvals in an active run.
Internal definition format remains an architecture choice; users see the plan.
Recurrence, cross-Agent orchestration, and conversation-to-workflow conversion
are not settled by the current on-demand prototype.

## Individual approvals and written steering

The normal sequential execution reaches a protected action and waits for one
decision. Do not manufacture a batch of pending approvals when the Agent has only
one waiting action. Multiple requests can arise from genuinely independent work;
bulk approval is not the default experience.

The approval card shows the exact proposed change, its target and parameters, its
effect, and the Agent's rationale. Approval releases only that action. It does not
mean the step or whole run has completed successfully.

The accepted design puts an optional written reply directly in the card:

- **Approve this action** authorizes the displayed proposal.
- **Decline** refuses that proposal without requiring an explanation.
- **Decline & send reply** also supplies reasoning or another direction, such as
  an internal task instead of a follow-up call, or skipping the current deal.

While a reply is drafted, the prototype disables Approve to prevent accidentally
treating guidance as approval. A changed protected proposal requires a fresh
decision. Show what changed and retain the declined proposal and exchange in the
run history. Feedback applies to this run; it does not silently change the saved
workflow or permanent Agent instructions.

Chat and the workflow view show the same request and decision. A decision made
in either surface appears in the other with actor/source attribution. A plain
Chat message is not implicitly an approval. Runtime behavior after a refusal
must support reconsideration, a new proposal, a permitted skip, or a clarification
request; it must not automatically equate refusal with stopping the whole run.
The prototype's scripted skip/revision branches are examples, not a fixed runtime
policy.

Canceling a run, declining an action, and stopping an Agent are separate controls.
Canceling a run does not stop the Agent or undo earlier external effects. Exact
stop/delete/suspension behavior still needs an architecture decision.

## Artifacts

Each step can produce an artifact, and the user can request one for individual
steps or for the workflow's final result. The preservation control is a
**Preserve artifact** switch followed, when enabled, by a multiline
**Describe the artifact** field.

The user describes content, format, structure, layout, or purpose in their own
words. For example: a branded PDF report, a spreadsheet with selected columns,
slides for leadership, an image, an archive, or another file type. Do not force
filename entry or a Document/Spreadsheet/Notes selector. Generated artifacts are
constrained by actual runtime capabilities, which the prototype does not prove;
unsupported or ambiguous requests need clarification rather than a misleading
success claim.

The run lists outputs with their source step, actual filename/type, readiness,
and **View** / **Download** controls. Partial results are labeled. Unfinished
outputs have no download action. Preserve the existing available files when a
later step fails or a run is canceled, subject to the eventual retention policy.
Chat may expose the same files; it must not create a separate copy of ownership
or access policy.

Preview depends on format. Download remains the common access path when a safe
preview is unavailable. A final artifact may use outputs from earlier steps.
Generation, preservation, and sending/publishing an artifact externally are
different operations: preserving a file is not approval to send it elsewhere.

## Unsettled product details

- When to ask for clarification about step goals or artifact descriptions.
- Supported initial operations, file-generation capabilities, and preview types.
- Limits for repeat proposals, parallel work, and human notification frequency.
- What happens when an approval expires or its target has materially changed.
- Artifact retention, deletion, sensitivity, and history after Agent deletion.
- Whether future policies may authorize a bounded class of actions in advance.

Permission handling in the prototype is illustrative. Apply the existing
[RBAC contract](../../features/rbac/IMPLEMENTATION-BRIEF.md) and decide actual
workflow permissions before implementation rather than copying its Editor/Viewer
switch into an API contract.
