# Repository discovery and release communication

This guide owns the maintainer steps for repository metadata, release-note
presentation, and starter-issue publication. It does not change deployment policy.
See [operations](operations.md#versioning-and-releases) for releases and
[CONTRIBUTING.md](../../CONTRIBUTING.md) for the public contribution process.

## Repository description and topics

The proposed values are in
[repository-metadata.json](../../.github/repository-metadata.json). This is a
reviewed input file, not an automatically applied GitHub configuration.

After approval, a repository administrator can apply it from the repository root
using an authenticated GitHub CLI and jq:

```bash
jq '{description, homepage}' .github/repository-metadata.json |
  gh api --method PATCH repos/aai-labs/agent-barn --input -
jq '{names: .topics}' .github/repository-metadata.json |
  gh api --method PUT repos/aai-labs/agent-barn/topics --input -
```

The second command replaces the entire topic set. Check for intentional changes
made in GitHub since review before applying it. Verify the About panel and topic
links in the public repository after saving. There is no background synchronization
or workflow that applies these values on merge.

Use product purpose, runtime, deployment, and supported integrations as topics.
GitHub supports at most 20 topics. Its default repository search covers name,
description, and topics; README text requires `in:readme`.
[GitHub search reference](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories) ·
[topic reference](https://docs.github.com/articles/classifying-your-repository-with-topics).

## Write release notes for users

Copy [the release-note template](../../.github/RELEASE_NOTES_TEMPLATE.md) into a
draft GitHub Release. Use a descriptive display title with the version, without
changing the release tag. Lead with shipped behavior, setup links, and upgrade
requirements, then retain the generated technical changelog and contributor
attribution. Check every benefit against the release tag, not current staging.

The existing Release Deploy Bundle workflow creates/updates a release with a
version-only name and generated notes. Apply the reviewed introduction and display
title after that workflow finishes, and check them again if it is rerun. Editing
release copy never changes tags, images, or deployments.

A [v0.22.0 introduction](../release-notes/v0.22.0-introduction.md) is a sample of
the template filled in for an existing release. If publishing it, keep the
release's existing technical changelog beneath the introduction.

## Publish approachable contributor tasks

The [starter-task drafts](../contributing/starter-tasks.md) are proposed issue
bodies. Before publishing one, search existing issues, confirm it is still needed,
and name a maintainer who agrees to answer questions. Publish each approved task
as a separate issue with the `good first issue` and `help wanted` labels, creating
those labels only if absent. Do not relabel complex runtime, security, migration,
or authorization bugs as beginner tasks to gain exposure.

Link the new issues from the contribution guide if needed. Close or update stale
ones and remove the beginner label if their scope grows. GitHub documents that
`good first issue` can help approachable issues surface in discovery:
[contributor label guidance](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/encouraging-helpful-contributions-to-your-project-with-labels).

## Recheck discovery

Capture visitors, unique cloners, referring sites, and popular content before
applying live metadata; retain weekly snapshots because GitHub's traffic view
covers 14 days. Track documentation visits and successful setup as well as stars.
Compare four weeks of results without attributing every change to metadata alone.
[GitHub traffic reference](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-traffic-to-a-repository).
