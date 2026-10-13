"""Isolated pinned LiteLLM with a mock model and its own disposable database."""

import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from testcontainers.postgres import PostgresContainer

from api.tests.core.givenpy import LambdaWith

IMAGE = "ghcr.io/berriai/litellm:v1.96.2"
MASTER_KEY = "sk-memory-budget-contract-master"


def pinned_litellm_budget_is_running():
    def step(context):
        database = PostgresContainer("postgres:16")
        directory = tempfile.TemporaryDirectory()
        config_file = Path(directory.name) / "config.yaml"
        config_file.write_text("""model_list:
  - model_name: openrouter/contract/model
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: contract-no-network
      mock_response: A deterministic response.
    model_info:
      input_cost_per_token: 1
      output_cost_per_token: 1
general_settings:
  master_key: sk-memory-budget-contract-master
""")
        context.litellm_container = None

        def start():
            database.start()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            context.litellm_url = f"http://127.0.0.1:{port}"
            context.litellm_container = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--network",
                    "host",
                    "-v",
                    f"{config_file}:/contract.yaml:ro",
                    "-e",
                    f"DATABASE_URL={database.get_connection_url().replace('+psycopg2', '')}",
                    IMAGE,
                    "--config",
                    "/contract.yaml",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"{context.litellm_url}/health/liveliness", timeout=2).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            raise AssertionError("Pinned LiteLLM did not become ready")

        def stop():
            if context.litellm_container:
                subprocess.run(["docker", "rm", "-f", context.litellm_container], check=False, capture_output=True)
            database.stop()
            directory.cleanup()

        return LambdaWith(start, stop)

    return step
