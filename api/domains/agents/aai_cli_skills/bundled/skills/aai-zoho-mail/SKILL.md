---
name: aai-zoho-mail
description: Use aai-cli email commands with Zoho Mail profiles to list, read, send, and delete Zoho messages.
---

# aai-cli Zoho Mail

Use this skill when working with Zoho Mail through `aai-cli email` and a Zoho Mail profile.

Always pass the intended Zoho Mail profile with `--profile` unless the active default profile is already known. `messages list` returns rich message objects that usually contain enough metadata to choose the next `messages get <MESSAGE_ID>` call.

Date filtering on `messages list` is client-side after fetching provider messages; check `truncated` when present.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, profile expectations, response notes, and examples.
