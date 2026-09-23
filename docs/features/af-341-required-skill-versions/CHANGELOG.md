# AF-341 Required Skill Versions — change log

Status: Completed
Epic: AF-341
Related context: [`../templates-and-skills.md`](../templates-and-skills.md), [`../af-253-agent-config-tuning/CHANGELOG.md`](../af-253-agent-config-tuning/CHANGELOG.md), [`../../guidelines/epics.md`](../../guidelines/epics.md)

## Current state

- Delivered: a Template Version applies together with every required-Skill change
  it implies — version moves, additions, and a group member the author picks —
  from the Agent configuration Template section, and Override authoring records a
  staged requirement without being judged against the Agent's live pins. Both
  deadlocks are resolved and the durable rules now live in
  [`../templates-and-skills.md`](../templates-and-skills.md).
- In transition: a Template Version that adds a required Skill declaring a
  provider the Agent holds no Secret for keeps Apply disabled until that
  credential is added in the Keys section. The Agent assignment would be refused
  by `validate_incoming_skill_providers`, so this blocks exactly what the server
  blocks; the Hire dialog collects such credentials inline, while Template
  selection does not.
- Next: none.
- Blockers: none.
- Deferred to the tracker: an Override author cannot choose *which* Skill Version
  to require (`_resolve_override_skill_map` takes the previous one, or latest on
  re-add); `required_providers` is lineage-latest rather than per-version, so a
  pin is judged against a Skill Version the Agent may not use; and inline
  credential capture on Template selection, which needs a Secrets field on
  `AgentTemplateSelection`.

## Changes

### 2026-09-23 — AF-341-03

- Delivered: the Template section also assigns required Skills the Agent does not
  hold. A standalone requirement is added at the version the snapshot records; a
  group with no assigned member offers its members and keeps Apply disabled until
  one is chosen. Additions appear in the Apply confirmation beside version moves.
- Changed: `agent-template-selection-settings.tsx` sends `skillIds` alongside
  `skillVersions` and replaces the missing-requirement blocker with the picker.
  No API change.
- Decision: Apply is disabled while an added Skill declares a provider the Agent
  has no Secret for. The server checks incoming assignments against the same
  lineage-latest provider data, so blocking here refuses exactly what the server
  would refuse rather than guessing.
- Coverage: two further Playwright specs cover a standalone addition riding along
  in one request, and Apply staying disabled until a group member is picked. The
  two existing `agent-detail-page` specs asserting Apply is disabled when required
  skills are missing pass unmodified — the credential gate now blocks the same
  scenario the assignment gate used to.

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
