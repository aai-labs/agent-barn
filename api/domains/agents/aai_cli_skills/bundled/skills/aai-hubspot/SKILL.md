---
name: aai-hubspot
description: Use aai-cli to inspect HubSpot CRM records, files, events, conversations, visitor identification, and custom channels.
---

# aai-cli HubSpot

Use this skill when working with HubSpot through `aai-cli hubspot`.

Before running commands, confirm the active profile or pass `--profile`. HubSpot profiles use `auth_type = "hubspot_service_key"` or `auth_type = "hubspot_legacy_private_app"` with `token_secret`.

HubSpot `401` and `403` errors include scope and auth-model remediation under `details`. Preserve that JSON when reporting failures. Custom channel commands are not supported for legacy private app tokens and return `unsupported_auth` before making a request.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, scopes, and failure handling.
