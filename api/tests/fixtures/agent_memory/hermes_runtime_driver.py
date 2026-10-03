"""Exercise the pinned Hermes turn loop without sending traffic to a real model."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/hermes")

from run_agent import AIAgent  # ty: ignore[unresolved-import]

agent = AIAgent(
    model="memory-contract-model",
    base_url=os.environ["CONTRACT_MODEL_URL"],
    api_key="contract-model-key",
    provider="custom",
    api_mode="chat_completions",
    enabled_toolsets=[],
    quiet_mode=True,
    skip_context_files=True,
    skip_background_review=True,
    session_id="new-memory-contract-session",
    platform="api",
)
native_prompt = (
    agent._memory_store.format_for_system_prompt("memory") + agent._memory_store.format_for_system_prompt("user")
    if agent._memory_store
    else ""
)
providers = [provider.name for provider in agent._memory_manager.providers] if agent._memory_manager else []
try:
    result = agent.run_conversation("What is our release convention? Please remember this conversation.")
finally:
    if agent._memory_manager:
        agent._memory_manager.shutdown_all()

settings = Path("/opt/data/hindsight/config.json")
print(
    "MEMORY_RUNTIME_CONTRACT="
    + json.dumps(
        {
            "providers": providers,
            "native_prompt": native_prompt,
            "response": result.get("final_response", ""),
            "saved_settings_exist": settings.exists(),
            "saved_credential": os.environ.get("MEMORY_API_KEY", "absent-credential") in settings.read_text()
            if settings.exists()
            else False,
        }
    )
)
