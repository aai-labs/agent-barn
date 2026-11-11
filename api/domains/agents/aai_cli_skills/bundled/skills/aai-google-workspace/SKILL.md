---
name: aai-google-workspace
description: Use the gog CLI to work with the Google Workspace services connected to this agent, such as Gmail, Calendar, Drive and Sheets.
---

# Google Workspace (gog)

Use this skill when working with Google Workspace through the `gog` CLI.

`gog` is a separate tool from aai-cli. It takes no `--profile`, and the account is already selected. The Google Workspace section of AGENTS.md lists the services connected to this agent.

Commands nest as `gog <service> <resource> <verb>`. Pass `--json` when you need to parse the output. Run `gog <service> --help` to discover subcommands instead of guessing.
