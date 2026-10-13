# MDP-119 workflow research

Status: Research; product direction agreed in discussion, architecture unselected.
Recorded: 2026-10-13.
Origin: [MDP-119 — Workflow + Playbook system](https://aai-labs.atlassian.net/browse/MDP-119).
Repository baseline: `d3e7b8e4` on `staging`.

This package preserves the design discussion before implementation. It describes
proposed behavior, not capabilities already delivered by Agent Barn. Existing
feature and architecture guides remain authoritative for current behavior. No
runtime upgrade, migration, release, or architecture decision is included.

## Read in this order

1. [Product design](product-design.md): the agreed audience, creation flow,
   individual approvals, written steering, and artifact experience.
2. [Approval architecture](approval-architecture.md): the primary proposal,
   alternatives, second opinion, enforcement gaps, and validation spike.
3. [Runtime research](runtime-research.md): current repository constraints and
   upstream Hermes/OpenClaw findings, including the TaskFlow removal.
4. [Interactive prototype](prototype.html): the accepted Agent page design with
   the latest artifact description controls. Open the file in a browser; it has
   inline CSS/JavaScript and needs no server or external dependencies.

The prototype contains fictional Sales Analyst/Pipedrive data. Its responses,
permissions, provider changes, downloads, and runtime transitions are simulated.
It is evidence of the intended interaction, not runtime feasibility. Earlier
generic dashboards, YAML authoring, bulk-approval defaults, and artifact format
selectors are superseded and are intentionally excluded.

## Evidence and limits

The original ticket called for a primary operator web UI, secondary chat
approvals, versioned definitions, database-owned state, deterministic/Agent/
approval/fanout steps, leased work items, external-effect idempotency, recovery
across crashes, a TaskFlow visibility mirror, and permission gates. It excluded a
drag-and-drop authoring designer. The current design adds nontechnical authoring
and arbitrary described artifacts; the TaskFlow dependency and implementation
acceptance criteria need reconciliation with the updated findings below.

- The original Jira description and comments were read on 2026-10-12. The
  attached implementation manual and mockup contents could not be retrieved:
  attachment access was denied. Reconcile them with these notes before treating
  the ticket as implementation-ready.
- The user explicitly settled the UI in this discussion. That direction
  supersedes the initial ticket's YAML-only authoring restriction for this
  proposal; it does not mean the external ticket has been updated.
- Sonnet 5.5 produced the accepted base design; subsequent iterations added
  artifacts and replaced filename/format forms with descriptions.
- Opus 5.5 gave a conceptual second opinion on approvals from a design-only
  brief. It did not inspect repository content or establish runtime capability.
- Desktop/mobile previews and focused JavaScript assertions exercised the
  simulated flows. No live provider calls, pinned-image workflow spike, or
  performance benchmark has been performed.
- External runtime documentation was checked on 2026-10-13. Documentation for
  current upstream releases is not evidence that our pinned images support it.

## Decisions still needed

Before implementation, select the execution principal and Permission mapping,
prove the runtime continuation and capability boundary, choose initial protected
operations, define lifecycle/expiry/recovery policy, and agree artifact retention
and storage. The engine/library choice follows that spike, not the mockup.

When this becomes a multi-PR implementation epic, create its coordination log
before the first implementation PR as required by
[the epic guideline](../../guidelines/epics.md). Record accepted consequential
architecture rationale under [the ADR rules](../../adr/README.md); these research
notes do not constitute an accepted ADR.
