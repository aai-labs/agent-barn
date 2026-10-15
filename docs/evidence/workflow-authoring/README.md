# AF-388 workflow authoring — UI evidence

Captured on 2026-10-15 from the rendered Next.js application using the repository
Playwright harness. Desktop viewport: 1440 × 1000; mobile: 390 × 844.
All identities, Agents and workflow data are synthetic browser fixtures. No live
provider, user data or credentials are shown.

| Screenshot | Behavior shown |
| --- | --- |
| [Manual editor](manual-editor.png) | Focused step editing, reorder/remove controls and explicit save |
| [Required inputs](required-inputs.png) | Typed inputs with labels and descriptions; internal keys stay hidden |
| [Saved cards](saved-workflow-cards.png) | Outcome, saved version and step/input counts |
| [Mobile cards](mobile-workflow-cards.png) | Responsive Agent header, horizontally scrollable tabs and workflow card |
| [Version history](immutable-version-history.png) | Current v2 and retained v1 with separate inspection controls |
| [Platform setting](platform-workflows-enabled.png) | Saved installation-wide choice alongside Agent Memory and Signup & trials |
| [Disabled workflows](workflows-disabled.png) | Agent navigation omits Workflows and displays an ordinary Agent tab |

Three temporary capture scenarios passed. Screenshots were inspected after capture.
CSS animations were disabled and the Next.js development indicator was hidden;
product content was not edited or composited. Version-history evidence starts
from an existing v1 fixture independently of the creation capture.

These images establish UI behavior, not database persistence or workflow execution.
The disabled-state scenario also asserts that workflow list/detail/history reads
are absent. Real API persistence, immutable snapshots, migration behavior and
authorization are covered by the integration suite described in the
[feature specification](../../features/agent-workflows.md) and
[epic change log](../../features/agent-workflows/CHANGELOG.md).
