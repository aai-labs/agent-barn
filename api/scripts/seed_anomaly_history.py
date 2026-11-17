"""Local dev fixture for trying anomaly detection by hand (AF-453).

Not part of the production or test code path. A fresh Agent is flagged for nothing
until it has been active on three different days, so this gives a real Agent five days
of steady activity (tool calls, model calls, `crm` reads, fetches from one host) and
runs a check that learns it. From then on, what the Agent does is judged against that
history: ask it to fetch a host it never used and the next check flags it.

`--spike` also adds an unusual few minutes just now (a burst of tool calls, half of
them failing, `crm` deletes, model calls and a new host), and runs a check that flags
it. Model-usage anomalies need the cost sync to have run recently, as they would live.

Seeded rows are marked (tool call session `anomaly-seed`, cost request ids
`anomaly-seed-…`), and `--clear` removes them together with the Agent's Anomalies,
ledger and check state, so it can start over. Each run first forgets the Agent's
check state, so the check relearns its history with the seeded rows in it.

Refuses to run against anything but a local installation and a database on this host.

Usage (from the repo root, with the dev stack's Postgres reachable, and detection on
for the Agent's Organization in Settings → Unusual activity):
    make seed-anomaly-history SEED_AGENT_ID=<agent id> [SEED_ARGS=--spike]
    make seed-anomaly-history SEED_AGENT_ID=<agent id> SEED_ARGS=--clear
"""

import argparse
import ipaddress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Session, col, select

from api.core.config import Config, get_config
from api.core.utils import create_injector
from api.domains.agents.models import Agent
from api.domains.anomalies.models import (
    AgentActivitySeen,
    AgentAnomaly,
    AgentAnomalyState,
    OrganizationAnomalySettings,
)
from api.domains.anomalies.service import AnomalyCheckService
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.costs.models import CostRecord
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

SEED_SESSION = "anomaly-seed"
SEED_REQUEST_PREFIX = "anomaly-seed-"
HISTORY_DAYS = 5
HISTORY_HOURS = (9, 10, 11)
USUAL_HOST = "usual.seed.example"
UNUSUAL_HOST = "unusual.seed.example"
INTEGRATION = "crm"
# How long before "now" the learning check pretends to run, so the spike seeded after
# it is stored after the point it read through.
LEARN_BEFORE = timedelta(minutes=10)


def _agent(session: Session, agent_id: UUID) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        raise ValueError(f"Agent {agent_id} was not found")
    return agent


def _tool_call(
    agent: Agent,
    at: datetime,
    tool_name: str,
    arguments: dict,
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
) -> ToolCall:
    row = ToolCall(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        session_id=SEED_SESSION,
        external_id=f"{SEED_SESSION}-{uuid4().hex}",
        tool_name=tool_name,
        arguments=arguments,
        status=status,
        occurred_at=at,
        completed_at=at,
    )
    row.created_at = at
    return row


def _fetch(agent: Agent, at: datetime, host: str, status: ToolCallStatus = ToolCallStatus.SUCCESS) -> ToolCall:
    return _tool_call(agent, at, "web_fetch", {"url": f"https://{host}/page"}, status)


def _crm(agent: Agent, at: datetime, verb: str) -> list:
    call = _tool_call(agent, at, "terminal", {"command": f"aai-cli {INTEGRATION} records {verb}"})
    action = BusinessAction(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        tool_call_id=call.id,
        ordinal=0,
        integration=INTEGRATION,
        resource="records",
        verb=verb,
        is_write=verb != "read",
        status=BusinessActionStatus.SUCCESS,
        occurred_at=at,
        completed_at=at,
    )
    action.created_at = at
    return [call, action]


def _model_call(agent: Agent, at: datetime, tokens: int) -> CostRecord:
    row = CostRecord(
        request_id=f"{SEED_REQUEST_PREFIX}{uuid4().hex}",
        litellm_key_hash=SEED_SESSION,
        occurred_at=at,
        spend=Decimal("0.001"),
        total_tokens=tokens,
        model="seed",
        status="success",
        agent_id=agent.id,
        organization_id=agent.organization_id,
    )
    row.created_at = at
    return row


def _spread(start: datetime, count: int, span: timedelta) -> list[datetime]:
    return [start + span * index / count for index in range(count)]


def _save(delegate: PostgresRepositoryDelegate, rows: list) -> None:
    with Session(delegate.engine) as session:
        for row in rows:
            session.add(row)
            # Tool calls before the Business Actions that point at them.
            session.flush()
        session.commit()


def seed_history(delegate: PostgresRepositoryDelegate, agent_id: UUID, now: datetime) -> None:
    """Three steady hours on each of the last five days: 10 fetches from one host and
    a `crm` read (11 tool calls), and 10 model calls of 1,000 tokens."""
    with Session(delegate.engine, expire_on_commit=False) as session:
        agent = _agent(session, agent_id)
        session.exec(sa.delete(AgentAnomalyState).where(col(AgentAnomalyState.agent_id) == agent_id))  # type: ignore[call-overload]
        session.commit()
    rows: list = []
    for day in range(1, HISTORY_DAYS + 1):
        for hour in HISTORY_HOURS:
            start = (now - timedelta(days=day)).replace(hour=hour, minute=0, second=0, microsecond=0)
            times = _spread(start, 10, timedelta(minutes=50))
            rows += [_fetch(agent, at, USUAL_HOST) for at in times]
            rows += _crm(agent, start + timedelta(minutes=55), "read")
            rows += [_model_call(agent, at, 1_000) for at in times]
    _save(delegate, rows)


def seed_spike(delegate: PostgresRepositoryDelegate, agent_id: UUID, now: datetime) -> None:
    """Six minutes, ending three minutes ago, unlike anything in the history: 150
    fetches, 90 of them failing and 5 from a new host, 25 `crm` deletes, and 80 model
    calls of 20,000 tokens."""
    with Session(delegate.engine) as session:
        agent = _agent(session, agent_id)
    times = _spread(now - timedelta(minutes=9), 150, timedelta(minutes=6))
    rows: list = []
    for index, at in enumerate(times):
        host = UNUSUAL_HOST if index < 5 else USUAL_HOST
        rows.append(_fetch(agent, at, host, ToolCallStatus.ERROR if index % 5 < 3 else ToolCallStatus.SUCCESS))
    for at in times[:25]:
        rows += _crm(agent, at, "delete")
    rows += [_model_call(agent, at, 20_000) for at in times[:80]]
    _save(delegate, rows)


def clear_seeded(delegate: PostgresRepositoryDelegate, agent_id: UUID) -> None:
    """Remove the seeded rows, and the Agent's Anomalies, ledger and check state."""
    with Session(delegate.engine) as session:
        statements = [
            # Business Actions go with their tool calls.
            sa.delete(ToolCall).where(col(ToolCall.agent_id) == agent_id, col(ToolCall.session_id) == SEED_SESSION),
            sa.delete(CostRecord).where(
                col(CostRecord.agent_id) == agent_id, col(CostRecord.request_id).startswith(SEED_REQUEST_PREFIX)
            ),
            sa.delete(AgentAnomaly).where(col(AgentAnomaly.agent_id) == agent_id),
            sa.delete(AgentActivitySeen).where(col(AgentActivitySeen.agent_id) == agent_id),
            sa.delete(AgentAnomalyState).where(col(AgentAnomalyState.agent_id) == agent_id),
        ]
        for statement in statements:
            session.exec(statement)  # type: ignore[call-overload]
        session.commit()


def _require_local(config: Config) -> None:
    host = config.db_connection_url.hosts()[0].get("host") or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not (config.is_local_installation and loopback):
        raise SystemExit("Refusing to seed: this is only for a local installation with its database on this host.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed anomaly-detection history for a local Agent.")
    parser.add_argument("--agent-id", required=True, type=UUID)
    parser.add_argument("--spike", action="store_true", help="Also seed an unusual few minutes just now.")
    parser.add_argument("--clear", action="store_true", help="Remove what was seeded and what it caused, and stop.")
    args = parser.parse_args()
    _require_local(get_config())

    injector = create_injector()
    delegate = injector.get(PostgresRepositoryDelegate)
    if args.clear:
        clear_seeded(delegate, args.agent_id)
        print(f"Cleared the seed for Agent {args.agent_id}.")
        return

    with Session(delegate.engine) as session:
        agent = _agent(session, args.agent_id)
        settings = session.exec(
            select(OrganizationAnomalySettings).where(
                col(OrganizationAnomalySettings.organization_id) == agent.organization_id
            )
        ).first()
    if settings is None or not settings.enabled:
        raise SystemExit("Turn on unusual activity checks for this Agent's Organization first (Settings).")

    checks = injector.get(AnomalyCheckService)
    now = datetime.now(UTC)
    seed_history(delegate, agent.id, now)
    checks.run_checks(now - LEARN_BEFORE)
    print(f"Seeded {HISTORY_DAYS} days of history for {agent.name}; the check has learned it.")
    if args.spike:
        seed_spike(delegate, agent.id, now)
        summary = checks.run_checks(now)
        print(f"Seeded a spike and checked {summary.agents} agents. See the Agent's Anomalies tab.")


if __name__ == "__main__":
    main()
