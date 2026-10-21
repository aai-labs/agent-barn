---
name: aai-merkys
description: Use aai-cli to ask Merkys questions and get grounded answers with cited sources, run deep research, and read its conversations, documents, data sources, and corpora.
---

# aai-cli Merkys

Use this skill when the answer should come from the organization's Merkys knowledge base (uploaded documents, connected Jira/Confluence/Drive/email sources, and the legal or medical corpora) instead of from your own memory or the web.

Before running commands, confirm the active profile or pass `--profile`. A Merkys profile uses a **user API key** sent in the `X-API-Key` header (`auth_type = "api_key_header"`) and needs a `base_url`. Everything you do is done as the key's owner: you only see what that user's role and access rules allow, and your questions appear in that user's conversation history.

## Which command

- `merkys ask "<question>"` — start here. One command creates a conversation, asks, and returns `{answer, sources, conversation_id, ...}`. Takes roughly 5–30 seconds.
- `merkys research start "<question>" --wait` — for broad questions that need several searches and a written report (about 1–5 minutes). It returns the finished run with `final_report`, `sources`, and `plan`. Without `--wait` it returns a `run_id` at once; check it later with `research get <run-id>`. If `--wait` times out the run keeps going: the error includes the `run_id`.
- `merkys conversations list|search|messages`, `documents list`, `sources list`, `assistants list` — look around: what was asked before, what is uploaded or connected.
- `merkys request GET <path>` — anything else read-only (legal corpus, case law, law commentary, medical corpus, statistics). See [the endpoint reference](references/api-endpoints.md).

## Reading an answer

- The answer text cites with `[[1]]`, `[[2]]`. Each number is the `index` of an entry in `sources`, which has `title`, `page_number`, `excerpt`, and `link` (empty for uploaded files). Quote sources by title and page.
- **Read the answer, not only the sources.** Merkys can reply "I don't know" and still return sources. Treat that as "not found", not as a result, and try a more specific question (names, terms, document titles) before giving up.
- If the key owner can see no matching content, the answer says it does not know. An empty `documents list` or `sources list` can also mean the key owner lacks access.
- To ask a follow-up in the same thread, pass `--conversation-id` from the earlier result.
- `warning: could not load sources` means the answer is valid but the sources lookup failed; run `conversations messages <conversation_id>` to fetch them.

## Errors

- `auth_error` / 401 — the API key is wrong, revoked, or for another deployment. Do not retry; tell the user.
- `config_error` — the profile has no `base_url`.
- `timeout` from `research start --wait` — not a failure of the run; use the `run_id` in `details` with `research get`.
- A research run with `status: "failed"` is returned as normal output; read `error_reason` and `failing_step`.

Successful output is JSON on stdout. Errors are structured JSON on stderr. See [the command reference](references/command-reference.md) for flags and real example output.
