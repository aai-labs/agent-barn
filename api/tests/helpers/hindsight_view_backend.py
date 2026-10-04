"""The pinned Hindsight image as a real backend for the memory viewer's list contract."""

import subprocess
import time
import uuid

import httpx

from api.core.config import get_config
from api.tests.core.givenpy import LambdaWith
from api.tests.helpers.hindsight_cost_bridge import IMAGE


def pinned_hindsight_is_running():
    """Runs Hindsight 0.10.2 with its embedded database and mock extraction model.

    The mock model turns each retained item into a few deterministic world facts, which
    is enough to exercise the real tag filter, total, search, and pagination SQL.
    """

    def step(context):
        if subprocess.run(["docker", "image", "inspect", IMAGE], check=False, capture_output=True).returncode:
            subprocess.run(["docker", "pull", IMAGE], check=True, capture_output=True)
        name = f"agentbarn-viewer-contract-{uuid.uuid4().hex[:8]}"
        config = get_config()
        previous_url, previous_key = config.hindsight_base_url, config.hindsight_api_key

        def start():
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "-p",
                    "127.0.0.1::8888",
                    "-e",
                    "HINDSIGHT_ENABLE_CP=false",
                    "-e",
                    "HINDSIGHT_API_LLM_PROVIDER=mock",
                    "-e",
                    "HINDSIGHT_API_LLM_API_KEY=viewer-contract",
                    IMAGE,
                ],
                check=True,
                capture_output=True,
            )
            port = (
                subprocess.run(["docker", "port", name, "8888/tcp"], check=True, capture_output=True, text=True)
                .stdout.split(":")[-1]
                .strip()
            )
            context.hindsight_url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"{context.hindsight_url}/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                logs = subprocess.run(["docker", "logs", name], check=False, capture_output=True, text=True).stdout[
                    -2000:
                ]
                subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
                raise AssertionError(f"Hindsight did not become healthy:\n{logs}")
            config.hindsight_base_url = context.hindsight_url
            config.hindsight_api_key = "viewer-contract-key"

        def stop():
            subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
            config.hindsight_base_url, config.hindsight_api_key = previous_url, previous_key

        return LambdaWith(start, stop)

    return step


def retain_in_bank(context, bank: str, content: str, tags: list[str], *, document_id: str | None = None) -> None:
    """Retain through Hindsight's own API, as the gateway would after forcing tags."""
    response = httpx.post(
        f"{context.hindsight_url}/v1/default/banks/{bank}/memories",
        json={
            "items": [{"content": content, "tags": tags, **({"document_id": document_id} if document_id else {})}],
            "observation_scopes": "per_tag",
        },
        timeout=60,
    )
    response.raise_for_status()


def hindsight_listing(context, bank: str, tag: str) -> dict:
    response = httpx.get(
        f"{context.hindsight_url}/v1/default/banks/{bank}/memories/list",
        params=[("tags", tag), ("tags_match", "any_strict"), ("limit", "100")],
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
