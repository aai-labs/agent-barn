DEFAULT_USER_MD = (
    "# USER\n\n<!-- Add details about the human(s) this agent works with. -->\n"
)
DEFAULT_TOOLS_MD = (
    "# TOOLS\n\n<!-- Local notes specific to this agent's tools and environment. -->\n"
)
# Appended to every agent's tools_md so the agent discovers the injected aai-cli skills.
# Path is relative to the openclaw workspace root, where TOOLS.md is written.
AAI_CLI_TOOLS_POINTER = (
    "\nIn order to access jira, confluence, bitbucket, github use the aai-cli tool. "
    "See ./skills/aai-cli/aai-cli_skill.md file.\n"
)
DEFAULT_AGENTS_MD = (
    "# AGENTS\n\n<!-- Workspace notes, conventions, and red lines for this agent. -->\n"
)
DEFAULT_BOOT_MD = (
    "# BOOT\n\n"
    "No startup actions configured. After processing the boot task, reply "
    "with the silent token `NO_REPLY` so the agent stays quiet on startup.\n"
)
DEFAULT_BOOTSTRAP_MD = "# BOOTSTRAP\n\n<!-- Add bootstrap configuration here. -->\n"
DEFAULT_HEARTBEAT_MD = "# HEARTBEAT\n\n<!-- Empty file — no heartbeat tasks. -->\n"
