---
name: aai-bitbucket
description: Use aai-cli to inspect and manage Bitbucket repositories, pull requests, branches, commits, source files, comments, and pipelines.
---

# aai-cli Bitbucket

Use this skill when working with Bitbucket Cloud through `aai-cli bitbucket`.

Before running commands, confirm the active profile or pass `--profile`. Repository commands accept `--repo`; newer commands also accept `--owner` plus `--repo`. A `workspace/repo` value overrides the configured workspace.

For pull request review work, start with `prs get`, inspect changed files with `prs diffstat`, fetch large diffs with `prs diff --output`, and read exact file contents with `source get <commit> <path>` before commenting.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and review workflows.
