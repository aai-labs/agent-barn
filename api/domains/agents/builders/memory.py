"""Configuration for the pinned runtime memory providers."""

from pathlib import Path

from kubernetes import client

MEMORY_COMMAND = '#!/bin/sh\nexec python3 /app/config/agentbarn_memory.py "$@"\n'
MEMORY_COMMAND_PATH = "/usr/local/bin/agentbarn-memory"


def memory_command_mount() -> client.V1VolumeMount:
    return client.V1VolumeMount(
        name="memory-command", mount_path=MEMORY_COMMAND_PATH, sub_path="agentbarn-memory", read_only=True
    )


def memory_command_volume(config_name: str) -> client.V1Volume:
    return client.V1Volume(
        name="memory-command",
        config_map=client.V1ConfigMapVolumeSource(
            name=config_name, items=[client.V1KeyToPath(key="agentbarn-memory", path="agentbarn-memory", mode=0o555)]
        ),
    )


MEMORY_WRITE_TOOL = (Path(__file__).parent.parent / "scripts" / "agentbarn_memory.py").read_text()
MEMORY_TOOL_INSTRUCTIONS = """

## Organization Memory

Automatic memory saves are private to this Agent. To explicitly save a durable
fact for the organization, run `/usr/local/bin/agentbarn-memory remember-organization` using
your terminal tool, with the fact on standard input (a quoted heredoc avoids
shell expansion). Only use this when the user requests an organization-wide
save. Never include credentials or secrets. The gateway requires
Organization Memory Read and write permission; having read access does not permit writing.
Always attempt this command for each requested shared save, even if a previous
attempt failed. Do not infer command availability or permissions from earlier
conversation messages. If the gateway refuses the save, explain that this Agent
lacks Organization Memory Read and write permission and an Owner or Admin must
grant it. Do not claim the fact was shared, or call a permission refusal a missing tool.
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
