"""Sequentially rebuild every running Agent workload for an operator maintenance task.

Run this inside the target ``agentbarn-api`` pod. The command is dry-run by
default and deliberately uses the Agent lifecycle service, so each rebuild
creates a fresh runtime Secret and ingest key.

Example::

    python -m api.scripts.rebuild_running_agents --namespace agent-farm-staging --apply
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from api.core.config import get_config
from api.core.utils import create_injector
from api.domains.agents.service import AgentService


def run(*, namespace: str, apply: bool) -> int:
    config = get_config()
    if namespace != config.k8s_namespace:
        raise ValueError(
            f"Requested namespace {namespace!r} does not match this API deployment's "
            f"K8S_NAMESPACE {config.k8s_namespace!r}"
        )

    service = create_injector().get(AgentService)
    agents, failures = service.rebuild_running_agents_for_maintenance(apply=apply)
    action = "Would rebuild" if not apply else "Rebuilt"
    for agent in agents:
        print(f"{action}: {agent.name} ({agent.id})")
    if not apply:
        print(f"Dry run complete: {len(agents)} running Agent(s) would be rebuilt.")
        return 0
    for agent, error in failures:
        print(f"FAILED: {agent.name} ({agent.id}): {error}")
    print(f"Maintenance complete: {len(agents)} rebuilt, {len(failures)} failed.")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--apply", action="store_true", help="Perform rebuilds; omit for a dry run.")
    args = parser.parse_args(argv)
    return run(namespace=args.namespace, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
