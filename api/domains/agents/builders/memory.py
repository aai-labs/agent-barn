"""Configuration for the pinned runtime memory providers."""

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
