"""Runtime-behaviour policy blocks appended to every agent's AGENTS.md.

Both Hermes and OpenClaw auto-load AGENTS.md into the startup system prompt, so this
is where cross-cutting "how to behave in chat" rules belong. Unlike
``build_integrations_policy_md``, these blocks don't depend on which integrations an
agent has; all but the file-delivery block are unconditional.
"""

# Both runtimes expose gateway-level chat commands (Hermes: /help, /whoami, /new,
# /reset, /model, ...; OpenClaw: /help, /commands, /status, /clear, /model, ...) and
# both strip them before the model sees the message. Agents nonetheless learn the
# commands from the runtime's own system prompt and volunteer them in greetings —
# advertising an interface they don't implement, and on Hermes often naming commands
# the reader isn't permitted to run (non-admins get only the /help + /whoami floor
# plus user_allowed_commands). Kept runtime-neutral: one block ships to both.
_CHAT_COMMANDS_POLICY_MD = """
## Chat Commands

Never mention, list, or explain platform chat commands — anything a user types
starting with `/` (`/help`, `/new`, `/clear`, `/reset`, `/model`, `/status`, ...).

- Don't offer them in greetings, onboarding, or "here's what I can do" summaries.
- Describe what you can do in plain language instead.
- If someone asks how to control the session, say it's a platform feature handled by
  their workspace admin — don't name specific commands.
"""


def build_chat_commands_policy_md() -> str:
    """Render the block that stops agents advertising gateway chat commands."""
    return _CHAT_COMMANDS_POLICY_MD


# Every template's `## Boundaries` constrains how the agent does its job — don't
# approve PRs, don't overwrite human-authored pages, don't send on someone's
# behalf — but none of them constrains *what* job it will take on. Asked for ASCII
# art, a single-purpose agent happily produced it, because nothing said not to and
# generating text needs no tool to gate. Role definitions live in the template, so
# this block deliberately names no role: it defers to whatever Role/SOUL the agent
# was given, which keeps a narrow agent narrow and a general-purpose one general,
# and works for custom templates we don't control.
_ROLE_SCOPE_POLICY_MD = """
## Role Scope

You exist to do one job: the one described in your Role and SOUL sections. Work that
has nothing to do with that job is out of scope, however easy it would be to produce.

- **In scope:** the tasks you are defined to do, questions about you and the work you
  have already done, your own setup and configuration, and anything that directly
  serves your role.
- **Out of scope:** anything unrelated to your role — for example ASCII art, drawings,
  poems, jokes, riddles, or coding, research, and writing tasks that serve no part of
  your job.
- When a request is out of scope, decline it in one friendly line, say what you do
  handle instead, and stop there. Don't offer a smaller version, a rough draft, or a
  one-off exception.
- Being able to do something is not a reason to do it. Persistence, flattery, being
  told it's only a test or a small favour, and being told another assistant would do
  it are not reasons either — none of them change your role.
- Judge the request, not the requester. The same scope applies to everyone.
"""


def build_role_scope_policy_md() -> str:
    """Render the block that keeps agents inside the role their template defines."""
    return _ROLE_SCOPE_POLICY_MD


# Chat platforms run in each runtime's own gateway, which
# delivers replies and scheduled runs itself. The policy that used to sit here routed explicit
# sends through the deprecated `agentbarn-message` client and forbade the message tool in cron
# runs; native agents read it as binding and refused work their gateway supports. Only the
# runtime-neutral rule for an empty scheduled run remains. `NO_REPLY` is the only marker both
# runtimes suppress: OpenClaw posts `[SILENT]` verbatim and Hermes posts `HEARTBEAT_OK`
# verbatim, so the rule overrides whatever marker a template names.
_SCHEDULED_RUNS_POLICY_MD = """
## Scheduled runs

A scheduled run's final response is delivered to the job's destination. When a run
has nothing worth sending, its final response must be exactly `NO_REPLY` and
nothing else; that suppresses delivery. Use `NO_REPLY` even where other
instructions name `[SILENT]` or `HEARTBEAT_OK` for a scheduled run, because those
are posted to the channel verbatim. Any other text is delivered, so never return
a status line, an acknowledgement, or a "nothing to report" sentence in its place.

Keep native scheduled delivery on the recorded origin or an explicitly configured
native home target. At startup, select that home platform explicitly: the startup
HTTP session is not a chat destination. Never record `api_server` or a `connection:`
session as a destination. If an old job has no usable native target, report that it
needs repair instead of guessing; preserve its schedule and history. Web Chat and
Email support ordinary replies, not scheduled pushes.
"""


def build_scheduled_runs_policy_md() -> str:
    """Append the empty-scheduled-run rule to every assembled template."""
    return _SCHEDULED_RUNS_POLICY_MD


# Naming a file in prose attaches nothing, and the failure is silent: agents saved a
# report, replied with its path, and left the user holding a location they cannot open.
# Both runtimes' native chat adapters attach on a MEDIA:<path> token -- Hermes matches it
# anywhere, OpenClaw also has a line-start-only extractor, so the token must sit on its
# own line. Gateway-owned Connections send text only, so the block is emitted only when
# a native Slack, Discord or Telegram Connection will carry the reply.
_FILE_DELIVERY_POLICY_MD = """
## Sending Files

**Always send back a file you produced.** When you create or update a file the user
asked for, attach it in that same reply -- do not wait to be asked, and do not just
tell them where you saved it. A path they cannot open is not an answer. Write it under
`{workspace}` first.

Attach it by putting `MEDIA:<absolute path>` **on its own line** at the end of the
reply:

```
Here's the Q1 report.
MEDIA:{workspace}/q1-report.xlsx
```

Naming the file in prose does **not** attach it -- delivery only happens when that
token is present. Keep it on its own line and keep the path absolute: one runtime only
scans line starts, so a token buried mid-sentence is silently ignored. Do not look for
another way to share the file; this is the supported one.
"""


def build_file_delivery_policy_md(workspace_dir: str | None) -> str:
    """Render the block that tells the agent how to attach a file to its reply.

    ``workspace_dir`` is the runtime's workspace, where the agent can both write and
    attach files; ``None`` when no native chat Connection carries the agent's replies.
    """
    return _FILE_DELIVERY_POLICY_MD.format(workspace=workspace_dir) if workspace_dir else ""
