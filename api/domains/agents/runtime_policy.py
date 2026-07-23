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
