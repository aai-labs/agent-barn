"""Replay the Barry incident locally, so the Activity tab can be read against a
case whose answer is already known.

Not part of the production/test code path. This reconstructs a real investigation:
an Agent that ran a 30-minute heartbeat around the clock for a week, resending a
large and steadily growing context on every call, with a separate 3-hourly scan
interleaved through it — then crash-looped, stopping all billing while the pod kept
restarting.

Two halves, because the tab reads two different sources:

* **Usage** — ``cost_record`` rows, written here. Heartbeat wakes at :29 and :59 of
  every hour, scan wakes on the 3-hour marks with a visibly different shape (more
  calls, much smaller prompts). Nothing inbound is written at all, so every wake is
  BACKGROUND. Billing stops at the crash and the window deliberately extends past
  it, so the cliff is visible rather than cropped out.
* **Runtime** — live pod state, which no database row can fake. ``--emit-manifest``
  prints a Deployment that crash-loops with the incident's own startup error; apply
  it to the dev cluster and the diagnostics panel reads it as it would a real one.

The shape is reproduced faithfully; the totals are not claimed to match the original
report to the digit. The source report's daily table and its final wake-by-wake table
are not mutually consistent (the last three hours alone hold more calls than the day
they belong to), so this replays the *mechanism* — two schedules, the growing static
context, the billing cliff — and prints what it actually produced.

Usage (from the repo root, with the dev stack's Postgres reachable):
    api/.venv/bin/python -m api.scripts.replay_barry_incident
    api/.venv/bin/python -m api.scripts.replay_barry_incident --clear
    api/.venv/bin/python -m api.scripts.replay_barry_incident --emit-manifest > /tmp/barry.yaml
"""

import argparse
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, col, delete, select

from api.core.config import get_config
from api.domains.agents.models import Agent, AgentAccess, AgentStatus, AgentType
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID
from api.domains.templates.models import PlatformTemplate
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.scripts.seed_activity_fixtures import (
    REQUEST_ID_PREFIX,
    _key_hash_for,
    _spend_for,
)

AGENT_NAME = "Barry (incident replay)"
MODEL = "openrouter/z-ai/glm-5.3"

# The incident, in UTC. The report is written in Addis Ababa time (UTC+3), where
# the heartbeats land on :29 and :59 — a whole-hour offset, so the minutes are the
# same either way and only the hour labels differ.
INCIDENT_START = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
LAST_CALL = datetime(2026, 9, 17, 11, 29, tzinfo=UTC)  # 14:29 EAT
CRASH_AT = datetime(2026, 9, 17, 11, 59, tzinfo=UTC)  # 14:59 EAT, pod recreated

HEARTBEAT_MINUTES = (29, 59)
SCAN_EVERY_HOURS = 3

# The heartbeat's prompt grows across the incident: the same context is resent every
# time *and* accumulates. This climb is why the average lands far below the maximum.
PROMPT_AT_START = 54_000
PROMPT_AT_END = 126_000

# The scan is the other schedule. Its wakes are the shape that gives it away —
# roughly twice the calls of a heartbeat, at a third of the prompt size.
SCAN_PROMPT_RANGE = (23_600, 54_600)
SCAN_CALLS = 7
HEARTBEAT_CALLS = (3, 4)

CRASHLOOP_MANIFEST = """\
# Crash-looping stand-in for the Barry incident, for reading the Activity tab's
# Runtime diagnostics panel against a pod that fails the way the original did.
#
#   kubectl -n agent-farm apply -f this-file.yaml
#   kubectl -n agent-farm delete deploy agent-{agent_id}
#
# The container name and the app label are what the diagnostics reader selects on.
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-{agent_id}
  namespace: agent-farm
  labels:
    app: agent-{agent_id}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: agent-{agent_id}
  template:
    metadata:
      labels:
        app: agent-{agent_id}
    spec:
      terminationGracePeriodSeconds: 1
      containers:
        - name: agent
          image: busybox:1.36
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "openclaw 0.7.0 starting"
              echo "workspace: /var/lib/openclaw (persistent volume)"
              echo "gateway: binding 0.0.0.0:8080"
              echo "ERROR Legacy workspace setup state requires migration ... run 'openclaw doctor --fix'"
              echo "fatal: workspace preflight failed; exiting before gateway ready"
              exit 1
"""


def _incident_wakes() -> list[tuple[datetime, bool]]:
    """Every wake start in the incident, flagged as a scan or a heartbeat."""
    wakes: list[tuple[datetime, bool]] = []
    moment = INCIDENT_START
    while moment <= LAST_CALL:
        if moment.hour % SCAN_EVERY_HOURS == 0 and moment.minute == 0:
            wakes.append((moment, True))
        if moment.minute in HEARTBEAT_MINUTES:
            wakes.append((moment, False))
        moment += timedelta(minutes=1)
    return wakes


def _heartbeat_prompt_base(moment: datetime) -> int:
    """Where the resent context had grown to by this point in the incident."""
    span = (LAST_CALL - INCIDENT_START).total_seconds()
    progress = (moment - INCIDENT_START).total_seconds() / span
    return int(PROMPT_AT_START + (PROMPT_AT_END - PROMPT_AT_START) * progress)


def _build_records(agent: Agent, organization_name: str | None, key_hash: str, rng) -> list[CostRecord]:
    records: list[CostRecord] = []
    for started_at, is_scan in _incident_wakes():
        calls = SCAN_CALLS if is_scan else rng.randint(*HEARTBEAT_CALLS)
        base = _heartbeat_prompt_base(started_at)
        moment = started_at
        for index in range(calls):
            if is_scan:
                prompt_tokens = rng.randint(*SCAN_PROMPT_RANGE)
                completion_tokens = rng.randint(300, 1_400)
                spacing = rng.randint(10, 60)
            else:
                # Tight within the wake: the same context, re-sent, plus whatever
                # the turn itself appended. This is the narrow band the wake row
                # shows as a min–max range.
                drift = 1 + rng.uniform(-0.006, 0.006) + 0.0025 * index
                prompt_tokens = int(base * drift)
                completion_tokens = rng.randint(40, 260)
                spacing = rng.randint(8, 40)
            duration_ms = rng.randint(2_000, 26_000)
            records.append(
                CostRecord(
                    request_id=f"{REQUEST_ID_PREFIX}-barry-{uuid.uuid4().hex}",
                    litellm_key_hash=key_hash,
                    occurred_at=moment,
                    ended_at=moment + timedelta(milliseconds=duration_ms),
                    spend=_spend_for(MODEL, prompt_tokens, completion_tokens),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    model=MODEL,
                    status="success",
                    call_type="acompletion",
                    request_duration_ms=duration_ms,
                    agent_id=agent.id,
                    organization_id=agent.organization_id,
                    agent_name=agent.name,
                    organization_name=organization_name,
                    source=CostRecordSource.LITELLM_LIVE,
                )
            )
            moment += timedelta(seconds=spacing)
    return records


def _ensure_agent(delegate: PostgresRepositoryDelegate, organization_id: uuid.UUID | None) -> Agent:
    """Barry, as RUNNING — the state a pod that started fine and crashed later is in.

    `AgentStatus.ERROR` is reserved for a failure to *provision*; a workload that
    came up and then began crash-looping keeps RUNNING in the database, and the pod
    is what carries the bad news. Diagnostics only reads the cluster for a RUNNING
    Agent, so this is also what makes the panel show anything at all.
    """
    config = get_config()
    with Session(delegate.engine) as session:
        if organization_id is None:
            organization = session.exec(select(Organization).order_by(col(Organization.created_at).asc())).first()
            if organization is None:
                raise SystemExit("No Organization in this database. Create one in the UI first.")
            organization_id = organization.id

        existing = session.exec(
            select(Agent).where(
                col(Agent.organization_id) == organization_id,
                col(Agent.name) == AGENT_NAME,
                col(Agent.deleted_at).is_(None),
            )
        ).first()
        if existing is not None:
            existing.status = AgentStatus.RUNNING
            session.add(existing)
            session.commit()
            return session.get(Agent, existing.id)  # type: ignore[return-value]

        memberships = list(
            session.exec(select(OrganizationUser).where(col(OrganizationUser.organization_id) == organization_id))
        )
        if not memberships:
            raise SystemExit(f"Organization {organization_id} has no memberships.")
        owner = next((m for m in memberships if m.role == OrganizationRole.OWNER), memberships[0])

        template = session.exec(select(PlatformTemplate).order_by(col(PlatformTemplate.version).desc())).first()
        if template is None:
            raise SystemExit("No Platform Templates. Start the API once so it seeds them, then re-run.")

        agent = Agent(
            organization_id=organization_id,
            created_by_user_id=owner.user_id,
            name=AGENT_NAME,
            status=AgentStatus.RUNNING,
            agent_type=AgentType.OPENCLAW,
            platform_template_id=template.id,
            model=config.agent_default_model,
        )
        session.add_all(
            [
                agent,
                AgentAccess(
                    organization_id=organization_id,
                    membership_id=owner.id,
                    agent_id=agent.id,
                    access_role_id=AGENT_OWNER_ROLE_ID,
                ),
            ]
        )
        session.commit()
        return session.get(Agent, agent.id)  # type: ignore[return-value]


def _report(records: list[CostRecord]) -> None:
    prompts = sorted(record.prompt_tokens for record in records)
    total_prompt = sum(prompts)
    total_completion = sum(record.completion_tokens for record in records)
    total_spend = sum((record.spend for record in records), Decimal(0))
    count = len(prompts)

    def percentile(fraction: float) -> int:
        return prompts[min(count - 1, int(fraction * (count - 1)))]

    print(f"\n  calls            {count:,}")
    print(f"  prompt tokens    {total_prompt / 1_000_000:.2f}M")
    print(f"  completion       {total_completion / 1_000:.0f}k")
    print(f"  spend            ${total_spend:.2f}")
    print(
        f"  prompt/call      avg {total_prompt / count:,.0f}  median {percentile(0.5):,}  "
        f"p95 {percentile(0.95):,}  max {prompts[-1]:,}"
    )
    print("\n  Per day (UTC):")
    by_day: dict[str, list[CostRecord]] = {}
    for record in records:
        by_day.setdefault(record.occurred_at.strftime("%b %d"), []).append(record)
    for day, rows in by_day.items():
        prompt = sum(row.prompt_tokens for row in rows)
        spend = sum((row.spend for row in rows), Decimal(0))
        print(f"    {day}   {len(rows):>4} calls   {prompt / 1_000_000:>6.2f}M prompt   ${spend:>5.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--organization-id", default=None)
    parser.add_argument("--seed", type=int, default=17, help="Random seed (default: 17, for a reproducible replay)")
    parser.add_argument("--clear", action="store_true", help="Remove a previous replay's rows first")
    parser.add_argument(
        "--emit-manifest",
        action="store_true",
        help="Print the crash-looping Deployment for the dev cluster and stop",
    )
    args = parser.parse_args()

    import random

    rng = random.Random(args.seed)
    delegate = PostgresRepositoryDelegate(get_config())
    organization_id = uuid.UUID(args.organization_id) if args.organization_id else None
    agent = _ensure_agent(delegate, organization_id)

    if args.emit_manifest:
        print(CRASHLOOP_MANIFEST.format(agent_id=agent.id))
        delegate.close()
        return

    if args.clear:
        with Session(delegate.engine) as session:
            removed = session.exec(
                delete(CostRecord).where(  # type: ignore[arg-type]
                    col(CostRecord.request_id).like(f"{REQUEST_ID_PREFIX}-barry-%")
                )
            )
            session.commit()
        print(f"Cleared {removed.rowcount} row(s) from a previous replay.")

    with Session(delegate.engine) as session:
        organization = session.get(Organization, agent.organization_id)
        organization_name = organization.name if organization else None

    key_hash = _key_hash_for(agent, get_config().agent_token_encryption_key)
    records = _build_records(agent, organization_name, key_hash, rng)

    print(f"Replayed the Barry incident onto {agent.name} ({agent.id}).")
    print(f"  {INCIDENT_START:%Y-%m-%d %H:%M} → {LAST_CALL:%Y-%m-%d %H:%M} UTC, billing stops at the crash.")
    # Summarise before the write: committing expires the instances, and they
    # detach when the Session closes.
    _report(records)

    with Session(delegate.engine) as session:
        session.add_all(records)
        session.commit()
    print(f"\n  Open: /dashboard/{agent.organization_id}/agents/{agent.id}?tab=activity")
    print(f"        set the range to {INCIDENT_START:%Y-%m-%d} → {(CRASH_AT + timedelta(days=1)):%Y-%m-%d}")
    print("\n  For the runtime half, apply the crash-looping pod:")
    print("        python -m api.scripts.replay_barry_incident --emit-manifest > /tmp/barry.yaml")
    print("        kubectl -n agent-farm apply -f /tmp/barry.yaml")
    delegate.close()


if __name__ == "__main__":
    main()
