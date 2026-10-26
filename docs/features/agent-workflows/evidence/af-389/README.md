# AF-389 UI evidence

Captured on 2026-10-21 after merging `origin/staging` at `58fcf60d`.
These screenshots show the implemented UI using synthetic responses from the
repository's Playwright workflow fixtures. They demonstrate presentation and
interaction; they are not evidence of live model execution. The earlier live
Hermes execution and its limitations are recorded in the [epic log](../../CHANGELOG.md).

| Screen | Evidence |
| --- | --- |
| Explicit version and input review | [Start run](01-start-run.png) |
| Step progression and timing | [Running](02-running.png) |
| Explicit cancellation confirmation | [Confirmation](03-cancel-confirmation.png) |
| Cancelled run with completed results retained | [Cancelled](04-cancelled.png) |
| Final persisted text result and elapsed times | [Completed](05-completed.png) |
| Individual completed step result | [Step summary](06-step-summary.png) |
| Narrow viewport | [Mobile](07-mobile.png) |

File artifacts, previews and downloads are deferred; the screenshots reflect
the current text-result scope.
