# USER.md - Team and Human Context

Learn about the team you document for. Update this file when stable context is
useful for future documentation work.
If the Required fields below are empty, the Setup Flow in AGENTS.md has not run
yet — it will trigger automatically on the next Slack message.

Integration credentials and base URLs are in TOOLS.md — do not duplicate them here.

## Team Context

### Required

- **Confluence space key** (where docs live):
- **Confluence parent page** (docs root / changelog location):
- **Slack channel for the weekly digest:**
- **Document from** (the earliest merge to ever document — a PR number/URL or a
  date; a permanent floor): defaults to the setup date when the operator says
  "from now". Resolve "from now" to a concrete date before writing it here so the
  floor is unambiguous.

### Repo Scope

Which repositories to document, from your configured source-control host (GitHub
or Bitbucket).

- **If the integration is already scoped to specific repos** (see the Integrations
  block in AGENTS.md), those are used automatically — leave this blank.
- **If it only has an owner/workspace and no repos**, list the repo slug(s) to
  document:
  - **Repos to document:**

### Additional Context

- **Team name:**
- **Jira project key(s)** (which keys count as ours, e.g. `AF`, `PLAT`):
- **How PRs reference a task** (e.g. the Jira key in the PR title or branch, like `AF-123`):
- **Default branch** (only if not each repo's default; usually auto-detected):
- **Weekly digest day/time:**
- **Doc page conventions** (naming, template, labels):

Treat every requester as a teammate. Be clear about what you documented versus
what you flagged as unclear.
