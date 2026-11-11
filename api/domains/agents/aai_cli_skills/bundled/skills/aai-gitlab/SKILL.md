---
name: aai-gitlab
description: Use aai-cli to inspect and manage GitLab projects, merge requests, issues, branches, commits, source files, notes, pipelines, and job logs on gitlab.com or a self-hosted instance.
---

# aai-cli GitLab

Use this skill when working with GitLab, on gitlab.com or a self-hosted instance, through `aai-cli gitlab`.

Before running commands, confirm the active profile or pass `--profile`. Project-scoped commands accept `--project`, which takes a numeric ID or a full path such as `group/subgroup/app`; without it they use `profile.repo`. GitLab has no separate workspace: always use the full path.

GitLab's terms apply: merge requests are `mrs`, and they are addressed by `iid`, the number shown in the UI, not `id`. Comments are `notes`.

For merge request review work, start with `mrs get`, read `mrs diffs` (use `--output` for large ones), read exact file contents with `source get <ref> <path>`, and check `mrs discussions list` for existing threads before commenting.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and review workflows.
