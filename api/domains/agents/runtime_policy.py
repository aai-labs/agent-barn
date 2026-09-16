"""Runtime-behaviour policy blocks appended to every agent's AGENTS.md.

Both Hermes and OpenClaw auto-load AGENTS.md into the startup system prompt, so this
is where cross-cutting "how to behave in chat" rules belong. Unlike
``build_integrations_policy_md``, these blocks are unconditional — they don't depend on
which integrations an agent has.
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


_MESSAGING_POLICY_MD = """
## Message Delivery

Agent Barn Communications owns Slack delivery. Never use provider tokens, direct
provider APIs, native send_message tools, or integration CLIs to send chat
messages. This delivery policy takes precedence over older transport
instructions in template content.

Ordinary responses are returned through the existing reply path. Send a separate
message only when the user explicitly requests it during the current inbound
execution. Use `agentbarn-message send --to <channel-or-person> --text <message>`;
add `--kind user` for a person or `--thread <thread-id>` for a thread. Name the
destination only: the message goes out on the same Connection the current
conversation arrived on, so never ask for, invent, or pass a Connection ID. That
also means a separate message stays inside the current workspace -- it cannot
reach a different Slack, Discord, or Telegram Connection. Use provider IDs when
names are ambiguous. The runtime supplies execution context and submission identity; never
create or override either.
Acceptance means queued, not delivered. Do not claim successful provider delivery
from a queue receipt. Other platforms do not support initiated sends yet.

Scheduled runs deliver too, and this is how recurring updates reach a home
channel: whatever a cron run returns as its final response is delivered
automatically. Write the update as the final response and it will be sent. A job
created while talking to someone in a channel or thread delivers back there; a job
created at startup, outside any conversation, delivers to the Agent's configured
default. The runtime records this when the job is created -- never state a
destination in the job prompt.

A job may be moved within the channel it was created in, and nowhere else. To post
at channel level instead of inside the thread, set the job's delivery to that same
channel with an empty thread, `<platform>:<channel-id>:`; to target a specific
thread, append it. Naming any other channel does not redirect the job, it stops it
delivering at all. To reach a different channel, ask the user to create the job from
there. When a run has nothing worth sending, return exactly the
silence marker your template already uses -- `[SILENT]`, `SILENT`, `NO_REPLY`,
`NO REPLY`, or `HEARTBEAT_OK`, in any case; each suppresses delivery. Any other text is delivered, so never return a status line,
an acknowledgement, or a "nothing to report" sentence in its place.

Do not call the message tool from a cron run. It is not a restriction on what
cron may send, it is a mechanism: the tool needs an active inbound execution to
send against, and a scheduled run has none. The final response is the delivery
path for scheduled work. If the Agent has no available default the submission is
rejected and an operator must configure or enable one in the Connection editor.
Never substitute another destination.
"""


def build_messaging_policy_md() -> str:
    """Append the shared Communications policy to every assembled template."""
    return _MESSAGING_POLICY_MD
