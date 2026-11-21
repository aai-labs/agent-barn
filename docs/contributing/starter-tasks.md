# Proposed first-contribution tasks

These are reviewable drafts, not open or assigned GitHub issues. A maintainer
must confirm each task is still needed, check for duplicates, and agree to sponsor
it before publication. Suggested labels after triage: `good first issue`,
`help wanted`, and `documentation`. Do not claim or implement a draft without a
published issue and a maintainer response.

The existing open backlog was checked on 16 November 2026. Runtime delivery,
credential migrations, and draft-editor bugs were not selected as beginner work.
Publication and maintainer assignment follow
[the maintainer guide](../guidelines/repository-discovery.md#publish-approachable-contributor-tasks).

## Draft 1: Explain configured Agent Sizes in memory troubleshooting

**Problem:** [local startup troubleshooting](../guidelines/local-troubleshooting.md)
says Agent pods request 320Mi and have a 1Gi limit. Those are the seeded Standard
values; the [Agent Size catalog](../features/agent-sizes.md) can provide different
resources. The current explanation can mislead a reader debugging OOMKilled.

**Scope:** Update that one troubleshooting entry to explain how to inspect the
running pod's actual requests/limits and compare them with the selected Agent
Size. Link the existing size contract rather than reproducing its settings.

**Acceptance criteria:**

- Standard values are identified as defaults, not universal limits.
- The entry explains that size changes apply on the next Agent start.
- The existing distinction between container OOM and Docker/node pressure remains.
- Commands contain placeholders, no real tenant identifiers or credentials.
- All relative links and commands are checked against the current source.

**Verification:** Documentation review and link/path checks; application tests are
unnecessary unless the contributor discovers a separate behavior defect.
**Maintainer sponsor:** Assign before publication; no sponsor has been committed.

## Draft 2: Verify and document the Windows WSL2 quick-start prerequisites

**Problem:** [the Windows section](../../README.md#windows) gives brief shell advice,
but the full stack also needs Docker integration, host-side storage bootstrap,
several free ports, and a compatible filesystem setup. A clean-machine checklist
would help first-time Windows contributors.

**Scope:** Run the documented local setup in a disposable WSL2 environment and
improve only the Windows-specific prerequisite/troubleshooting guidance. Preserve
the authoritative command sequence in the README; do not redesign startup.

**Acceptance criteria:**

- Record Windows/WSL distribution and Docker Compose versions tested.
- Verify Docker Desktop integration, Bash, Git, uv/Python bootstrap, kubectl,
  OpenSSL, and curl requirements against run.sh and the README.
- Explain the symptom and corrective action for any reproduced setup failure.
- Separate untested steps from verified startup and provider-dependent Agent work.
- Use development-only configuration and redact secrets from evidence.

**Starting points:** [run.sh](../../run.sh), [local quick start](../../README.md#quick-start),
[Windows guidance](../../README.md#windows), and
[Garage operations](../guidelines/garage.md).
**Verification:** A dated setup transcript without secrets and checked links.
**Prerequisites:** Windows/WSL2, Docker, disk space; provider credentials only if
validating real model execution. Do not run cleanup against an existing install.
**Maintainer sponsor:** Assign before publication; no sponsor has been committed.

## Draft 3: Add a documented, synthetic screenshot for per-agent costs

**Problem:** The [per-agent cost walkthrough](../use-cases.md#track-per-agent-model-costs)
explains synchronization and attribution but has no accompanying cost-screen
image. A small, labelled example would make the relevant fields easier to find.

**Scope:** Capture the existing Agent Costs UI using synthetic browser fixtures.
Add one image and a short caption alongside the walkthrough; do not change UI or
billing behavior. Reuse the project's fixture approach rather than live customer
or provider data.

**Acceptance criteria:**

- Show the Agent, reporting range, spend, and model-call context legibly.
- Use synthetic names/values and include no credentials, real identities, or URLs.
- Give the image meaningful alt text and identify it as fixture-based UI evidence.
- Record the source commit, fixture/test used, and reproducible capture steps.
- Explain that displayed spend is imported, can lag, and is not a provider invoice.

**Starting points:** [Agent detail browser tests](../../ui/tests/e2e/agent-detail-page.spec.ts),
[Costs fixtures](../../ui/tests/pages/data-support/cost-data-support.po.ts),
[Costs contract](../features/costs.md), and
[testing prerequisites](../guidelines/testing.md).
**Verification:** Open the captured image, check its data and caption, and validate
links. Run a focused browser check if capture requires fixture changes.
**Maintainer sponsor:** Assign before publication; no sponsor has been committed.
