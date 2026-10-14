# The trial onboarding script lives in a hidden Platform Template

Status: Accepted
Date: 2026-10-12
Origin: AF-373 (first conversation script, Free trial Stage 1)

A new trial user's first Agent needs a first-conversation script that makes no sense for any other Agent, so it lives in a dedicated built-in Platform Template, `trial-onboarding`, that Organizations never see and only the trial onboarding flow creates Agents from. This departs from [2026-07-28](2026-07-28-global-predefined-templates.md), under which every Organization sees every Platform Template.

## Considered alternatives

- **A visible built-in template** (or a new version of `general-purpose`): any Organization could hire an Agent that greets its user as a newly signed-up trial user. Rejected by the maintainer as meaningless outside onboarding.
- **Script held in onboarding code, sent only to the onboarding Agent**: no admin-editable content, and the API would need its own marker for "the onboarding Agent". Rejected in favour of keeping prompt content in a template Platform Administrators can edit without a deploy.

## Consequences

- Hiding is a code-owned key list (`HIDDEN_TEMPLATE_KEYS`), not a schema column: the one hidden lineage is seeded by the file-based bootstrap, and no other template needs it.
- Organization template reads filter the key in the query and answer 404 for it; Platform Administrator routes are unchanged.
- Revisit if a second hidden template appears, or if Organizations need to fork onboarding content.
