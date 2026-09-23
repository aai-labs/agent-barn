# AF-341 Required Skill Versions — change log

Status: Active
Epic: AF-341
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../af-253-agent-config-tuning/CHANGELOG.md`](../af-253-agent-config-tuning/CHANGELOG.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: Override authoring no longer judges a staged requirement against the
  Agent's live pins, and the Agent configuration Template section applies a
  Template Version together with the required Skill pins it bumps, listing those
  version moves in the Apply confirmation. The reported deadlock is resolved.
- In transition: a Template Version that requires a Skill the Agent does not have
  at all still blocks Apply and sends the user to the Skills section first.
- Next: AF-341-03, the Template section adding a newly required Skill in the same
  request, with a member picker for requirement groups.
- Blockers: none.

## Changes

### 2026-09-23 — AF-341-02

- Delivered: selecting a Template Version from the Agent configuration Template
  section carries the required Skill pins that version demands, so an Agent moves
  from Template v1/Skill v1 to Template v2/Skill v2 in one apply. The confirmation
  dialog lists each version move before it is written, and the Skills section's
  read-only version control now points at the Template section instead of
  advising a step that could not work.
- Changed: `agent-template-selection-settings.tsx` derives the pin changes and
  sends them as `skillVersions`; `agent-skills-tab.tsx` carries the replacement
  hint. No API change — the endpoint already accepted these fields.
- Decision: only *changed* pins are sent. An incoming pin is provider-checked
  against the Skill lineage's latest requirements, so resending matching pins
  would fail Template switches that succeed today.
- Decision: a requirement group is left untouched when an assigned member already
  sits at its required version; a member beyond that version is the caller's
  business and is never pulled back. When no assigned member satisfies the group,
  the first in snapshot order is moved and named in the confirmation.
- Coverage: three Playwright specs in `ui/tests/e2e/agent-configuration-page.spec.ts`
  cover the bump carrying its pin, a satisfied group being left alone, and the
  Skills section staying locked with the new hint.

### 2026-09-23 — AF-341-01

- Delivered: Override Draft save and Override publish accept a required Skill
  Version newer than the Agent's current pin; selecting that Override Version
  still refuses unless the matching Skill pins arrive in the same request.
- Changed: `SelectionValidator.validate_override_requirements` asks for exact
  version match only from a caller that supplied prospective pins; presence,
  visibility and provider rules are unchanged for every caller. Docs updated in
  [`../templates-and-skills.md`](../templates-and-skills.md) and
  [`../af-253-agent-config-tuning/CHANGELOG.md`](../af-253-agent-config-tuning/CHANGELOG.md).
- Decision: authoring records intent and does not make a requirement live —
  publishing an Override Version does not activate it, so the live-pin check
  belongs at `select_agent_template`, not at draft save or publish.
- Coverage: two integration tests in `api/tests/integration/test_agents.py` cover
  draft save and publish accepting the newer requirement, and selection refusing
  it without pins then accepting it with them. The existing publish-presence,
  unpublished-skill and source-update tests pass unmodified.
- Follow-up: an Override author still cannot choose *which* version to require —
  it is the previous one, or the Skill's latest on re-add
  (`_resolve_override_skill_map`). Needs a version on the draft-update DTO;
  tracked separately.
