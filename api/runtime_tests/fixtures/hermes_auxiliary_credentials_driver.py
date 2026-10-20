"""Report which key Hermes resolves for its main model and each auxiliary task.

Runs inside a Hermes image with Agent Barn's generated config and runtime Secret. Prints
JSON naming, per task, whether the resolved key is the runtime's LiteLLM key; the keys
themselves are never printed.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import yaml

HOME = "/tmp/hermes-home"
os.makedirs(HOME, exist_ok=True)
shutil.copy("/contract/config.yaml", f"{HOME}/config.yaml")
os.environ["HERMES_HOME"] = HOME
os.chdir("/opt/hermes")
sys.path.insert(0, "/opt/hermes")

from agent.auxiliary_client import get_text_auxiliary_client  # ty: ignore[unresolved-import]
from agent.background_review import _resolve_review_runtime as resolve_review_fork  # ty: ignore[unresolved-import]
from agent.curator import _resolve_review_runtime as resolve_curator_binding  # ty: ignore[unresolved-import]
from hermes_cli.runtime_provider import resolve_runtime_provider  # ty: ignore[unresolved-import]

RUNTIME_KEY = os.environ["OPENAI_API_KEY"]
config = yaml.safe_load(Path(f"{HOME}/config.yaml").read_text())
tasks = json.loads(Path("/contract/tasks.json").read_text())
main_model = config["model"]
main = resolve_runtime_provider(requested=main_model["provider"], target_model=main_model["model"])


class _Agent:
    """The fields the review fork reads from the agent it forks."""

    provider = main_model["provider"]
    model = main_model["model"]

    def _current_main_runtime(self):
        return main


def _resolve(task: str):
    if task == "background_review":
        return resolve_review_fork(_Agent(), config.get("auxiliary", {}).get(task) or {})["api_key"]
    if task == "curator":
        binding = resolve_curator_binding(config)
        return resolve_runtime_provider(
            requested=binding.provider,
            target_model=binding.model,
            explicit_api_key=binding.explicit_api_key,
            explicit_base_url=binding.explicit_base_url,
        ).get("api_key")
    client, _ = get_text_auxiliary_client(task)
    return getattr(client, "api_key", None) if client else None


def _classify(key) -> str:
    return "runtime_key" if key == RUNTIME_KEY else "other"


print(
    json.dumps(
        {
            "main": _classify(main.get("api_key")),
            "tasks": {task: _classify(_resolve(task)) for task in tasks},
        }
    )
)
