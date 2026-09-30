---
name: aai-openpanel
description: Use aai-cli to read OpenPanel projects, raw event exports, aggregated insights (metrics, pages, referrers, devices, geo), and user profiles.
---

# aai-cli OpenPanel

Use this skill when working with OpenPanel analytics through `aai-cli openpanel`.

This is a **read-only** integration — there are no write endpoints (no `identify`/`track` calls, no project or client management). Always pass the intended profile with `--profile` unless the active default profile is already known.

OpenPanel clients are typed `write`, `read`, or `root` server-side, and this matters for which commands work with a given profile:
- `projects list` / `projects get` (the Manage API) require a `root` client.
- `events export`, all `insights *` commands, and `profiles *` commands require a `read` or `root` client.
- A project's default `write` client fails every command here with `401`/`403`.

`insights *` and `profiles *` commands need a project ID in the URL — pass `--project-id` or set `profile.project_id` to avoid repeating it. `events export`'s `--project-id` is optional: omit it when the profile's client is already scoped to a single project.

`insights pages`/`referrers`/`devices`/`geo` accept `--limit`/`--cursor` but the provider ignores them — those four always return every breakdown row for the date range, unsorted. To answer a "top N" question, fetch all rows, then sort and slice client-side. Only `events export` really paginates, and a `{ "name": null, ... }` breakdown row is the "no value for this dimension" bucket, not an error.

Successful output is JSON on stdout, wrapped in an `_aai.pagination` metadata block added by this CLI. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, response notes, and examples captured from a live OpenPanel workspace.
