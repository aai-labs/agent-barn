# AF-341 Required Skill Versions — change log

Status: Active
Epic: AF-341
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../af-253-agent-config-tuning/CHANGELOG.md`](../af-253-agent-config-tuning/CHANGELOG.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: Override authoring no longer judges a staged requirement against the
  Agent's live pins, so a required Skill Version above the Agent's assignment can
  be drafted and published. Exact-version enforcement remains at selection.
- In transition: the Agent configuration Template section still sends a Template
  selection without the required Skill pins, so a Template Version that bumps a
  required Skill Version cannot yet be applied from the UI.
- Next: AF-341-02, the Template section carrying required Skill pins and showing
  the resulting version moves before applying.
- Blockers: none.

## Changes

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
