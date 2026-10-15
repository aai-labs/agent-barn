# AF-387 Agent workflows — change log

Status: Active
Epic: [AF-387](https://aai-labs.atlassian.net/browse/AF-387)
Related context: [Feature specification](../agent-workflows.md), [live architecture](https://aai-labs.atlassian.net/wiki/spaces/AF/pages/3067248652), [RBAC](../rbac/IMPLEMENTATION-BRIEF.md)

## Current state

- Delivered in this change: [AF-388 / WF01](https://aai-labs.atlassian.net/browse/AF-388) Agent-owned definitions, immutable schema-v1 versions, validated step/input schemas and manual authoring/inspection through the Agent’s Workflows tab. Opus 5.5 reviews approved the manual-only implementation and direct-editor simplification; merge is pending; no earlier slice is claimed as landed.
- In transition: Delivery scope was narrowed on 2026-10-15 to defer natural-language draft generation to a separate PR. There are no generation endpoints, model adapter, request records or model settings in this slice. Authoring uses a persisted Platform Admin setting, falling back to the deployment default until a choice is saved. Execution, actual artifacts, approvals and notifications remain unavailable.
- Next: A separate generation PR and [AF-389 / WF02 — Run workflows and view real outputs](https://aai-labs.atlassian.net/browse/AF-389). Execution needs its own isolation, durability, output and acceptance gates.
- Blockers: None in WF01. Merge coordination remains pending.

## Changes

### 2026-10-15 — AF-388 — PR preparation and screenshot evidence

- Evidence: Added [seven inspected screenshots](../../evidence/workflow-authoring/README.md) covering editor/inputs, desktop/mobile saved cards, immutable-version history, Platform enablement and hidden disabled navigation. The real rendered UI uses synthetic request fixtures; three capture scenarios passed. No live persistence or execution is inferred from screenshots.
- Verification: Latest affected runs passed 64 workflow/settings/public-contract API tests, 29 Platform trial settings API tests and 148 workflow/Platform settings/Agent detail browser tests. API lint/format/types, UI types/lint, migration-head and whitespace checks passed; full suites were not repeated after the follow-ups.
- Scope: Excluded an unrelated inherited memory-test change from the PR diff. Preserved the original committed MDP-119 research files without alteration. No release or deployment changes accompany PR preparation.


### 2026-10-15 — AF-388 — hide disabled Workflows UI

- Changed: The Agent Workflows tab and its content require the enabled installation capability as well as Agent read permission. Disabled direct/legacy links fall back to an available Agent tab without fetching workflow content. A failed capability read hides the tab; existing capability-cache freshness still applies.
- Scope: UI visibility only, per user clarification. Existing API reads, mutation admission and saved data are unchanged.
- Verification: Both direct and legacy-link regressions failed on the visible tab before the fix, then passed. All 148 workflow, Platform workflow settings and Agent detail browser scenarios passed; UI types/lint and whitespace checks passed.


### 2026-10-15 — AF-388 — staging integration

- Changed: Merged staging through `fdb9b670`, preserving the uncommitted WF01 work. Platform Settings now extends staging’s existing composition with Workflows alongside Agent Memory and Signup & trials. Onboarding routes, trial cleanup and both sets of public API operations are retained.
- Schema: Merge revision `c32e42bb0396` joins workflow head `a38802d7f002` and staging head `d72b85f19c40`. The earlier migration-merge follow-up is resolved. Historical-schema preservation checks use SQL for columns present at that revision rather than the current Agent ORM model.
- Verification: 64 focused workflow/settings/public-contract API tests, 29 Platform trial settings API tests and 45 workflow/Platform Settings browser scenarios passed after integration. API lint/format/types, UI types/lint, the migration-head check and whitespace checks passed.
- Follow-up: WF01 remains pending review on the updated branch; merge/deployment coordination remains pending. No release or running database changes accompany the integration.


### 2026-10-15 — AF-388 — Platform workflow authoring setting

- Delivered: Platform Settings → Workflows provides an explicit Save/Cancel authoring toggle across Organizations. A saved choice overrides the environment default without a redeploy. Disabling authoring blocks creation, new versions and archive while preserving inspection; existing Agent authority remains required, and execution stays unavailable.
- Changed: Two Platform Admin GET/PUT operations, singleton settings migration `a38802d7f002` after `a38801c6e001`, atomic Platform-scoped audit events, effective capability/action checks and workflow-cache invalidation. The shared Platform Settings page now composes separate Agent Memory and Workflow sections.
- Verification: All 64 focused workflow, Platform Memory settings and public-contract API tests passed, including persistence, immediate admission, admin/read-only-key authority, audit projection/rollback and migration preservation. All 35 workflow and Platform Settings browser scenarios passed. API lint/format/types, UI types/lint, migration-head and whitespace checks passed.
- Follow-up: Generation and execution remain deferred. No release, deployment or runtime change accompanies this setting.


### 2026-10-15 — AF-388 — completion of query and validation follow-up

- Delivered: List/history page positions survive reload through validated URL parameters; returning from a definition retains the list page. Invalid page values fall back to page one, empty out-of-range pages offer first-page recovery, and legacy workflow links retain page parameters. List summaries and lazy query/cache behavior from the preceding improvement remain in place.
- Verification: Browser regressions first failed at the missing page URL parameters, then passed for reload, return navigation and invalid/out-of-range page recovery. All 26 workflow browser scenarios passed, including long and non-Latin labels persisting distinct valid internal keys without exposing them. The completion API run passed all 33 workflow/public-contract tests; API lint/format/types, UI types/lint and the migration-head check also passed. Earlier full-suite results below predate these improvements.
- Follow-up: No new review was started. The delegated improvement run ended at the Claude provider limit; no final Opus opinion is claimed for these improvements. No execution/generation, release or deployment changes accompany this follow-up.


### 2026-10-15 — AF-388 — validation, query and component improvements

- Changed: Fields explain errors after blur and save validation retains its section links. Hidden input-key normalization accepts ordinary punctuation, numeric starts, accents, long labels and non-ASCII labels; collisions identify the matching input label. Existing saved snapshots remain unchanged.
- Queries: Workflow cards consume a compact, tenant-scoped SQL summary projection. List/history reads occur only in their visible views. Structured scoped keys and a 30-second freshness window support cache reuse; successful saves seed the detail cache from the response, while scoped lists/history and mutation authority/conflict failures invalidate appropriately. Organization switching evicts workflow caches. Server pagination remains 20 by default/100 maximum; the subsequent completion follow-up adds URL page state.
- Components: Cards, list, history, pager, text fields, input editor and save-error presentation have separate feature-local components; the shared section rail still serves editing and saved inspection.
- Verification: Opus’s implementation run recorded 23 passing workflow browser scenarios and a passing walkthrough capture. The parent completed 33 passing API/public-contract tests, API/UI static checks and the migration-head check, and synchronized the documentation. The delegated run and its continuation hit Claude API rate limits before a final opinion; no Opus approval is claimed for these improvements.


### 2026-10-15 — AF-388 — workflow cards and internal input keys

- Changed: Workflow definitions appear as individual responsive cards with outcome descriptions, step/input counts, saved versions and archive status. Cards open the saved definition. Input keys stay internal in editing and saved inspection; label edits still derive them automatically and validation directs users to the label.
- Verification: All 20 workflow browser scenarios pass, including card summaries/navigation and hidden keys with persisted derivation; UI types/lint also pass. No review is requested, per the user’s instruction.


### 2026-10-15 — AF-388 — label-derived input keys

- Changed: Input labels derive read-only keys in the editor (trim, lowercase, whitespace to hyphens). Label changes update the draft key; existing keys remain intact until their label changes. API/UI validation now accepts hyphens alongside existing underscores; uniqueness and length limits remain enforced.
- Verification: Browser regression reproduced the old unchanged key after a label edit. All 29 workflow API tests and 19 workflow browser scenarios pass, as do API lint/format/types and UI types/lint. No additional review is requested, per the user’s instruction.


### 2026-10-15 — AF-388 — manual authoring and Agent tab integration

- Delivered: **Create workflow** → directly enter/edit workflow details, outcome, steps, typed inputs and output descriptions → explicitly save an immutable version. Add/remove/undo the most recent removal/reorder all retain edited fields. A shared numbered step rail and focused panel support both editing and saved inspection; compact Overview/Version history tabs share the divider baseline, and archive uses the actions menu. Creation fills the content width. Validation opens and links invalid sections with one-based field labels, retains edits and blocks invalid client submissions; API errors use the same panel labels. Removal preserves keyboard focus; lost save authority disables edits while retaining draft section navigation.
- Navigation/authority: Workflows is an Agent tab alongside Chat and Memory, governed by `agent.read` independently of `activity.read`. Existing `/workflows` links redirect to `?tab=workflows` and retain the selected definition. Leaving the tab clears the definition query. URL Organization/Agent identity keys embedded state; Organization switching drops unsaved drafts. Header metadata/actions wrap and tabs scroll on narrow screens. Viewers inspect; Editors author through current effective permissions. Query keys and invalidation remain scoped by Organization/Agent.
- Changed: `api/domains/workflows/`, seven additive public authoring/read operations and their operation inventory, and `ui/src/features/workflows/`. Unreleased migration `a38801c6e001` follows `c42e91b7a603`, adds definition/version constraints and immutable-version protection, and preserves existing Agents. Generation-specific code, tests, unreleased table creation and configuration were removed with the scope reduction. Saved definitions/versions are unchanged by that removal.
- Configuration: `WORKFLOW_AUTHORING_ENABLED=false` by default; local ignored configuration explicitly sets it true and the recreated API reports authoring enabled for Archie. `.env.spec`, Helm/Helmfile and [operations](../../guidelines/operations.md#workflow-authoring-wf01) document the gate. No workflow model/provider credentials or runtime image changes are required.
- Verified: API lint/format/types, migration head check, UI types/lint and Helm renders with the installation gate both off/on pass. The final manual-only full suites passed: 4,443 API tests with one existing skip and 718 browser tests; 30 focused API/contract tests also passed. Opus 5.5 round 7 approved with two documentation corrections, now applied. The subsequent direct-editor change has a browser regression that failed on the hidden Workflow name field before the fix; all 18 focused workflow browser tests and UI types/lint pass for the simplified creation flow. Opus 5.5 round 8 approved that final UI change with no blocking or required findings.
- Evidence: Screenshots and recording use the real UI with browser fixture data; the walkthrough records direct manual creation, section editing, removal/undo, saving and immutable version inspection.
- Follow-up: Coordinate the merge; staging has a sibling migration branch and will require `make merge-heads` when integrating there. No version bump, run start, provider effect or unrelated ticket change accompanies WF01.
