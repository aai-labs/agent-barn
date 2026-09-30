---
name: aai-github
description: Use aai-cli to inspect and manage GitHub repositories, issues, pull requests, reviews, branches, source files, and Actions logs.
---

# aai-cli GitHub

Use this skill when working with GitHub through `aai-cli github`.

Before running commands, confirm the active profile or pass `--profile`. GitHub profiles normally provide `owner` and `repo`; most commands also accept `--owner` and `--repo` overrides.

For pull request review work, start with `prs get`, inspect changed files with `prs files`, fetch large diffs with `prs diff --output`, and read exact file contents with `source get <sha> <path>` before posting comments or reviews.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and review workflows.
