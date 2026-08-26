---
name: aai-gmail
description: Use aai-cli email commands with Gmail REST profiles to list, read, send, and delete Gmail messages.
---

# aai-cli Gmail

Use this skill when working with Gmail through `aai-cli email` and a Gmail REST profile.

Always pass the intended Gmail profile with `--profile` unless the active default profile is already known. `messages list` returns message stubs; use `messages get <MESSAGE_ID>` to read decoded subject and body content.

Date filters on `messages list` are translated to Gmail search syntax. Send commands accept typed flags or documented JSON payloads.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for command shapes, profile expectations, response notes, and examples.
