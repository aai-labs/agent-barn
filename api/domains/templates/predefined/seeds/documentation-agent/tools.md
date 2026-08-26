# TOOLS.md - Local Notes for {{ agent_display_name }}

This file records integration-specific notes for the Documentation Agent.

## Expected Integrations

- Jira: read a task for context — description, acceptance criteria, links — using
  the Jira key found on a pull request.
- Source control (GitHub or Bitbucket): find merged pull requests and read what
  shipped — the changed files, the diff, the commits under a PR, and file
  contents (including md files) at a ref. Whichever host is configured is used.
- Confluence: create and update documentation pages and the changelog, and check
  whether a task/PR is already documented.
- Slack: post the weekly digest of what shipped.

## Skill Index

Use service-specific skills before calling any external integration CLI. Do not
guess CLI syntax from memory if a skill file is available. Read the relevant
skill file first:

- Jira: `./skills/aai-jira/SKILL.md` for `aai-cli jira` (always pass
  `--profile jira-work`).
- Source control — use whichever host is configured (see the Integrations block
  in AGENTS.md). Both expose the same capabilities:
  - GitHub: `./skills/aai-github/SKILL.md`, `--profile github-work`. Key
    commands: `repos get` (default branch), `prs list --sort updated` (then filter
    to merged), `prs files` (files changed), `prs diff`, `prs commits`,
    `source get`.
  - Bitbucket: `./skills/aai-bitbucket/SKILL.md`, `--profile bitbucket-work`.
    Key commands: `repos get` (mainline branch), `prs list --sort updated` (then
    filter to merged), `prs diffstat` (files changed), `prs diff`, `prs commits`,
    `source get`.
  The authoritative profile-to-repo/owner mapping is in the Integrations block of
  AGENTS.md and the `## Configured Integrations` section below — don't guess repo
  slugs.
- Confluence: `./skills/aai-confluence/SKILL.md` for `aai-cli confluence`
  (always pass `--profile confluence-work`) — `pages get` (read the changelog
  for the dedup backstop), `pages list`, `pages create` / `pages update`
  (docs + changelog), and attachments.
  **Page bodies (`--body`) are Confluence _storage format_ (XHTML) — NOT Markdown
  and NOT JSON.** Use real tags: `<h2>`/`<h3>` headings, `<p>` paragraphs,
  `<ul><li>` lists, `<a href="...">` links, and a code macro for code blocks
  (`<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[ ... ]]></ac:plain-text-body></ac:structured-macro>`).
  Markdown (`##`, `**`, ` ``` `) renders as literal text, so don't use it.
  **Page links:** don't hand-build a page URL from the bare site — Confluence
  Cloud pages live under `/wiki`. Take the link straight from the `pages create` /
  `pages get` response: `_links.base` (already ends in `/wiki`, e.g.
  `https://<site>.atlassian.net/wiki`) + `_links.webui` (`/spaces/<KEY>/pages/<id>/...`).
  A link missing the `/wiki` segment 404s. Note `pages list` strips `_links`, so
  read the link from `pages get`/`pages create`, not from a list result.
- Slack: use the built-in Slack integration configured during agent setup.

## CLI Policy

External access is performed through the `aai-cli` tool, documented by the skill
files above. Prefer commands that return normalized JSON. For writes, follow the
Safety Rules and the service-specific skill instructions.

## Safety Rules

- Read Jira and the source-control host freely within configured permissions.
- Only create or update **your own** auto-generated Confluence pages and the
  changelog. Never edit or overwrite pages a person authored.
- Clearly mark auto-generated pages as such, with links to the pull request and
  the Jira task they came from.
- Before creating a page, dedup: check the `memory/documented.json` ledger
  first, then the changelog page (see AGENTS.md) — never create a duplicate.
- When a change is too unclear to document, write a placeholder that flags what a
  human needs to fill in — never invent behavior.
- **Never paste raw tool output into a page.** aai-cli returns JSON and `prs diff`
  returns patch text — these are inputs you read, not page content. Always
  synthesize prose in Confluence storage format (XHTML). A page body that is
  literal JSON, a raw diff, or Markdown source is a bug, not a document.
- Never write credentials into memory files or published pages.
