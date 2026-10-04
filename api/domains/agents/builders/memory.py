"""Configuration for the pinned runtime memory providers."""

from pathlib import Path

MEMORY_WRITE_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_memory.py").read_text()
MEMORY_TOOL_INSTRUCTIONS = """

## Organization Memory

Automatic memory saves are private to this Agent. To explicitly save a durable
fact for the organization, run `agentbarn-memory remember-organization` using
your terminal tool, with the fact on standard input (a quoted heredoc avoids
shell expansion). Only use this when the user requests an organization-wide
save. Never include credentials or secrets. The gateway requires a separate
Organization Memory write grant; having read access does not permit writing.
If refused, explain the missing permission and do not claim the fact was shared.
Acceptance means extraction is queued, not that the memory is already recallable.
Other Agents need Organization Memory read access to recall it. This command
cannot write as another Agent or modify another Agent's private memories.
"""

MEMORY_PLUGIN_PATH = "/opt/openclaw-preinstalled/npm/node_modules/@vectorize-io/hindsight-openclaw"
MEMORY_RETAIN_CONTEXT = (
    "Keep durable facts, user preferences, decisions, and working conventions from this conversation. "
    "Skip greetings, transient progress, credentials, and secrets. Agent IDs, session IDs, channels, "
    "providers, and tags are routing metadata rather than names of people or organizations."
)


def hermes_memory_settings() -> dict:
    return {
        "mode": "local_external",
        "bank_id": "agentbarn",
        "auto_recall": True,
        "auto_retain": True,
        "recall_sync": True,
        "retain_every_n_turns": 1,
        "retain_context": MEMORY_RETAIN_CONTEXT,
        "observation_scopes": "per_tag",
        "recall_budget": "low",
        "recall_max_tokens": 1024,
        "recall_types": ["world", "experience", "observation"],
        "recall_indicator": False,
        "retain_indicator": False,
    }


def openclaw_memory_settings() -> dict:
    return {
        "hindsightApiUrl": "${MEMORY_URL}",
        "hindsightApiToken": "${MEMORY_API_KEY}",
        "dynamicBankId": False,
        "bankId": "agentbarn",
        # Bank administration belongs to the gateway/operator, not a runtime.
        "bankMission": "",
        "autoRecall": True,
        "autoRetain": True,
        "retainEveryNTurns": 1,
        "retainRoles": ["user", "assistant"],
        "retainToolCalls": False,
        "retainContext": MEMORY_RETAIN_CONTEXT,
        "recallBudget": "low",
        "recallMaxTokens": 1024,
        "recallTypes": ["world", "experience", "observation"],
        "enableKnowledgeTools": False,
        "logLevel": "warning",
        "debug": False,
    }
