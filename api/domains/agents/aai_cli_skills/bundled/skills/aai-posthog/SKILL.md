---
name: aai-posthog
description: Use aai-cli to query PostHog product analytics, read projects, execute HogQL event queries, list saved insights, inspect persons and cohorts, read team dashboards, and view release annotations.
---

# aai-cli PostHog

Use this skill when working with PostHog product analytics through `aai-cli posthog`.

Before running commands, confirm the active profile or pass `--profile`, `--project-id`, or environment variables `POSTHOG_API_KEY`, `POSTHOG_PROJECT_ID`, and `POSTHOG_HOST`.

PostHog integration is read-first for product decision-making, idea discovery, and release impact correlation. Prefer typed subcommands for discovering projects, saved team insights, cohorts, dashboards, and annotations. For custom analytics, use `posthog events query` with HogQL queries or raw JSON query payloads.

List commands aggregate PostHog pagination up to `--limit` and preserve the provider response shape (`count`, `next`, `previous`, `results`).

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, query examples, and output shapes captured from a PostHog workspace.
