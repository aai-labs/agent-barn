"""Local dev fixture generator for the Agent Activity tab.

Not part of the production/test code path. ``seed_cost_fixtures`` scatters rows at
random offsets, which is right for the Costs pages but useless here: Activity groups
calls into *wakes* by the gaps between them, so randomly spaced rows collapse into
one wake per call and every derived figure — cadence, trigger split, prompt spread —
becomes noise.

This script writes rows with deliberate temporal structure instead. Each target Agent
is given a **persona**, and the personas are chosen to put the tab's diagnostics
side by side in one window:

* ``runaway-loop``    — wakes every few minutes around the clock, prompts pinned at a
                        huge near-identical size, no messages anywhere near them. This
                        is the case the tab exists to catch: it trips the background
                        callout, and the prompt-size panel shows p95 ≈ median ≈ max.
* ``context-bloat``   — a real person is driving it, but every call resends an enormous
                        static context. Healthy cadence, healthy trigger split, and the
                        money still leaks. Only the prompt-size panel shows it.
* ``healthy``         — bursts during business hours, each preceded by an inbound
                        message, prompts growing inside a wake the way a conversation
                        does. The control case: this is what fine looks like.
* ``nightly-cron``    — one substantial wake a day, nobody asking. Background, but a
                        legitimate schedule rather than a loop — the distinction the
                        cadence figure is there to let you make by eye.

Spend is derived from the tokens at per-model rates rather than drawn at random, so
the money on the page is consistent with the token counts beside it.

By default it attaches personas to the Agents already in the database, rotating
through them. ``--create-agents`` instead makes one stopped, headless Agent per
persona — named for what it demonstrates — so all four can be read side by side on a
database that only has one real Agent. Inbound messages reuse the Agent's own
Communication Connection where it has one, and otherwise get a disabled, retired
fixture connection — retired so no live machinery adopts it, present because
``agent_chat_message.connection_id`` is a non-null FK.

Safe to re-run: every row it writes is tagged, and ``--clear`` removes exactly those.
The demo Agents are idempotent by name and are *not* removed by ``--clear``, since
deleting an Agent is a bigger decision than dropping some fixture rows.

Usage (from the repo root, with the dev stack's Postgres reachable):
    make seed-activity
    make seed-activity SEED_ACTIVITY_ARGS="--create-agents --clear"
    uv run --project api python -m api.scripts.seed_activity_fixtures --list-agents
    uv run --project api python -m api.scripts.seed_activity_fixtures \
        --agent-id <uuid> --persona runaway-loop
"""

import argparse
import hashlib
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlmodel import Session, col, delete, select

# Writing an Agent configures its mapper, which resolves every foreign key it
# declares — so the whole model set has to be registered first, exactly as
# `migrations/env.py` registers it. Keep this list in step with that one.
import api.domains.agent_settings.models
import api.domains.auth.models
import api.domains.events.models
import api.domains.events.security_audit
import api.domains.rbac.models
import api.domains.shared_credentials.models
import api.domains.skills.models
import api.domains.tool_calls.models
from api.core.config import get_config
from api.domains.agents.models import Agent, AgentAccess, AgentStatus, AgentType
from api.domains.communications.models import CommunicationConnection
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID
from api.domains.templates.models import PlatformTemplate
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

import api.domains.users.models  # noqa: F401  isort:skip

# Everything this script writes carries one of these, and --clear matches on them.
# Nothing else in the database starts with either prefix.
REQUEST_ID_PREFIX = "gen-activity-seed"
MESSAGE_ID_PREFIX = "activity-seed"
FIXTURE_CONNECTION_NAME = "Activity fixtures (seeded)"

# $ per 1M tokens, (prompt, completion). Right order of magnitude per tier, so a
# 96k-token prompt on a mid-tier model costs what it ought to.
MODEL_RATES: dict[str, tuple[float, float]] = {
    "openrouter/anthropic/claude-opus-5": (15.00, 75.00),
    "openrouter/anthropic/claude-sonnet-5": (3.00, 15.00),
    "openrouter/z-ai/glm-5.2": (0.60, 2.20),
    "openrouter/z-ai/glm-5.3": (0.58, 2.20),
    "openrouter/openai/gpt-5-mini": (0.25, 2.00),
}

# Wakes for the user-driven personas land inside these hours, Monday to Friday.
WORK_START = time(8, 0)
WORK_END = time(18, 30)


@dataclass(frozen=True)
class Persona:
    """One recognisable way an Agent can spend money."""

    key: str
    headline: str
    model: str
    # Gap between the starts of consecutive wakes, and how much it wanders. A small
    # jitter reads as a schedule on the cadence figure; a large one reads as demand.
    wake_every: timedelta
    jitter: float
    calls_per_wake: tuple[int, int]
    # Seconds between calls inside a wake. Must stay well under WAKE_GAP_SECONDS
    # (300) or the burst splits into one wake per call.
    call_spacing: tuple[int, int]
    # Prompt size: a floor, the random spread above it, and how much it grows with
    # each further call in the same wake. Zero spread and zero growth is the
    # fingerprint of one large static context resent verbatim every time.
    prompt_floor: int
    prompt_spread: int
    prompt_growth: int
    completion: tuple[int, int]
    # Whether an inbound message is written just before each wake. This, and only
    # this, is what makes the wake read as USER rather than BACKGROUND.
    user_driven: bool
    business_hours: bool


PERSONAS: dict[str, Persona] = {
    "runaway-loop": Persona(
        key="runaway-loop",
        # Six, not the four you might reach for: two wakes closer together than
        # WAKE_GAP_SECONDS (300) are one wake by definition, so a tighter loop
        # would show up as a single enormous burst rather than a fast cadence.
        headline="wakes every ~6 minutes, nobody asking, same huge prompt every time",
        model="openrouter/anthropic/claude-sonnet-5",
        wake_every=timedelta(minutes=6),
        jitter=0.08,
        calls_per_wake=(3, 5),
        call_spacing=(4, 20),
        prompt_floor=96_000,
        prompt_spread=1_400,
        prompt_growth=0,
        completion=(180, 620),
        user_driven=False,
        business_hours=False,
    ),
    "context-bloat": Persona(
        key="context-bloat",
        headline="a person is driving it, but every call resends an enormous context",
        model="openrouter/anthropic/claude-opus-5",
        wake_every=timedelta(minutes=35),
        jitter=0.55,
        calls_per_wake=(2, 4),
        call_spacing=(8, 45),
        prompt_floor=118_000,
        prompt_spread=3_000,
        prompt_growth=450,
        completion=(220, 1_500),
        user_driven=True,
        business_hours=True,
    ),
    "healthy": Persona(
        key="healthy",
        headline="bursts when someone asks, prompts growing the way a conversation does",
        model="openrouter/z-ai/glm-5.2",
        wake_every=timedelta(minutes=24),
        jitter=0.85,
        calls_per_wake=(2, 6),
        call_spacing=(6, 60),
        prompt_floor=1_800,
        prompt_spread=1_400,
        prompt_growth=5_200,
        completion=(120, 1_800),
        user_driven=True,
        business_hours=True,
    ),
    "nightly-cron": Persona(
        key="nightly-cron",
        headline="one substantial run a day, nobody asking — a schedule, not a loop",
        model="openrouter/openai/gpt-5-mini",
        wake_every=timedelta(hours=24),
        jitter=0.02,
        calls_per_wake=(6, 11),
        call_spacing=(10, 90),
        prompt_floor=11_000,
        prompt_spread=9_000,
        prompt_growth=2_800,
        completion=(400, 2_600),
        user_driven=False,
        business_hours=False,
    ),
}

# The order personas are handed out in when the caller does not choose. The loop
# comes first so a single-Agent database still shows the case that matters most.
DEFAULT_ROTATION = ["runaway-loop", "healthy", "context-bloat", "nightly-cron"]

# Demo Agents created by --create-agents, one per persona. Named for what they
# demonstrate, so the Agent list reads as a legend for the tab.
DEMO_AGENT_NAMES: dict[str, str] = {
    "runaway-loop": "Runaway Loop (demo)",
    "context-bloat": "Context Bloat (demo)",
    "healthy": "Healthy Agent (demo)",
    "nightly-cron": "Nightly Cron (demo)",
}

MESSAGES = [
    "can you take a look at this?",
    "what happened with the deploy last night?",
    "summarise the thread for me",
    "any idea why that job keeps failing?",
    "pull the numbers for last week please",
    "is this still blocked?",
]


def _spend_for(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    prompt_rate, completion_rate = MODEL_RATES.get(model, (1.0, 3.0))
    dollars = (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000
    return Decimal(f"{dollars:.12f}")


def _key_hash_for(agent: Agent, encryption_key: str) -> str:
    """SHA-256 of the Agent's LiteLLM key — the join key the sync job builds."""
    try:
        return hashlib.sha256(decrypt_token(agent.litellm_key_encrypted, encryption_key).encode()).hexdigest()
    except Exception:
        # A key encrypted under a rotated secret. The column is display-only for
        # Activity, which joins on agent_id, so a stable synthetic hash is enough.
        return hashlib.sha256(str(agent.id).encode()).hexdigest()


def _in_business_hours(moment: datetime) -> bool:
    return moment.weekday() < 5 and WORK_START <= moment.timetz().replace(tzinfo=None) <= WORK_END


def _wake_starts(persona: Persona, window_start: datetime, now: datetime, rng: random.Random) -> list[datetime]:
    """Wake start times across the window, spaced the way the persona behaves."""
    starts: list[datetime] = []
    moment = window_start
    while moment < now:
        if not persona.business_hours or _in_business_hours(moment):
            starts.append(moment)
        step = persona.wake_every.total_seconds()
        step *= 1 + rng.uniform(-persona.jitter, persona.jitter)
        # Never let jitter pull two wakes closer than the grouping threshold, or
        # the persona's own cadence stops being what the page reports.
        moment += timedelta(seconds=max(step, 360))
    return starts


def _connection_for(
    delegate: PostgresRepositoryDelegate,
    agent: Agent,
    cache: dict[uuid.UUID, uuid.UUID],
) -> uuid.UUID:
    """The Agent's own Connection where it has one, else a retired fixture Connection.

    `agent_chat_message.connection_id` is a non-null FK with ON DELETE RESTRICT, so
    a message needs one. The fixture Connection is created disabled and retired: it
    satisfies the constraint without any live ingress machinery adopting it.
    """
    if agent.id in cache:
        return cache[agent.id]
    with Session(delegate.engine) as session:
        existing = session.exec(
            select(CommunicationConnection)
            .where(col(CommunicationConnection.agent_id) == agent.id)
            .order_by(col(CommunicationConnection.retired_at).is_(None).desc())
        ).first()
    if existing is not None:
        cache[agent.id] = existing.id
        return existing.id

    now = datetime.now(UTC)
    connection = CommunicationConnection(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        platform_key="slack",
        display_name=FIXTURE_CONNECTION_NAME,
        enabled=False,
        retired_at=now,
        credentials_encrypted=f"{REQUEST_ID_PREFIX}-credentials",
        driver_key_encrypted=f"{REQUEST_ID_PREFIX}-driver-key",
    )
    delegate.save(connection)
    cache[agent.id] = connection.id
    return connection.id


def _build_wake(
    *,
    agent: Agent,
    organization_name: str | None,
    persona: Persona,
    started_at: datetime,
    key_hash: str,
    rng: random.Random,
) -> list[CostRecord]:
    """One burst of calls, spaced closely enough to group into a single wake."""
    calls = rng.randint(*persona.calls_per_wake)
    records: list[CostRecord] = []
    moment = started_at
    for index in range(calls):
        prompt_tokens = persona.prompt_floor + rng.randint(0, persona.prompt_spread) + persona.prompt_growth * index
        completion_tokens = rng.randint(*persona.completion)
        duration_ms = rng.randint(1_200, 38_000)
        records.append(
            CostRecord(
                request_id=f"{REQUEST_ID_PREFIX}-{uuid.uuid4().hex}",
                litellm_key_hash=key_hash,
                occurred_at=moment,
                ended_at=moment + timedelta(milliseconds=duration_ms),
                spend=_spend_for(persona.model, prompt_tokens, completion_tokens),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                model=persona.model,
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
        moment += timedelta(seconds=rng.randint(*persona.call_spacing))
    return records


def _build_messages(
    *,
    agent: Agent,
    connection_id: uuid.UUID,
    started_at: datetime,
    ended_at: datetime,
    rng: random.Random,
) -> list[AgentChatMessage]:
    """An inbound message just before the wake, and the reply just after it.

    The inbound one is what makes the wake read as USER — it has to land inside
    ``[started_at - USER_LEAD_SECONDS, ended_at]``, so it goes a plausible handful
    of seconds ahead of the first call rather than at the same instant.
    """
    asked_at = started_at - timedelta(seconds=rng.randint(4, 70))
    replied_at = ended_at + timedelta(seconds=rng.randint(1, 8))
    session_key = f"agent:main:slack:channel:seed-{agent.id.hex[:8]}"
    return [
        AgentChatMessage(
            agent_id=agent.id,
            connection_id=connection_id,
            openclaw_msg_id=f"{MESSAGE_ID_PREFIX}-{uuid.uuid4().hex}",
            session_key=session_key,
            channel_id="C-SEED",
            channel_name="#seeded-activity",
            direction=MessageDirection.INBOUND,
            conversation_type=ConversationType.CHANNEL,
            sender_id="U-SEED",
            sender_name="Seeded Teammate",
            content=rng.choice(MESSAGES),
            occurred_at=asked_at,
        ),
        AgentChatMessage(
            agent_id=agent.id,
            connection_id=connection_id,
            openclaw_msg_id=f"{MESSAGE_ID_PREFIX}-{uuid.uuid4().hex}",
            session_key=session_key,
            channel_id="C-SEED",
            channel_name="#seeded-activity",
            direction=MessageDirection.OUTBOUND,
            conversation_type=ConversationType.CHANNEL,
            content="Had a look — details above.",
            occurred_at=replied_at,
        ),
    ]


def _target_agents(
    delegate: PostgresRepositoryDelegate,
    agent_ids: list[uuid.UUID],
    organization_id: uuid.UUID | None,
    limit: int,
) -> list[Agent]:
    with Session(delegate.engine) as session:
        query = select(Agent).where(col(Agent.deleted_at).is_(None))
        if agent_ids:
            query = query.where(col(Agent.id).in_(agent_ids))
        elif organization_id is not None:
            query = query.where(col(Agent.organization_id) == organization_id)
        agents = list(session.exec(query.order_by(col(Agent.created_at).asc())))
    return agents if agent_ids else agents[:limit]


def _ensure_demo_agents(
    delegate: PostgresRepositoryDelegate,
    organization_id: uuid.UUID | None,
) -> list[tuple[Agent, Persona]]:
    """One stopped, headless Agent per persona, so the tab can be read side by side.

    Stopped and template-pinned exactly the way the Agent UI would create them: the
    pin is not optional (``ck_agent_template_pin_state``), and STOPPED keeps this
    from trying to start a workload. Idempotent by name.
    """
    config = get_config()
    pairs: list[tuple[Agent, Persona]] = []
    with Session(delegate.engine) as session:
        if organization_id is None:
            organization = session.exec(select(Organization).order_by(col(Organization.created_at).asc())).first()
            if organization is None:
                raise SystemExit("No Organization in this database. Create one in the UI first.")
            organization_id = organization.id

        membership = session.exec(
            select(OrganizationUser)
            .where(col(OrganizationUser.organization_id) == organization_id)
            .order_by(col(OrganizationUser.created_at).asc())
        ).first()
        if membership is None:
            raise SystemExit(f"Organization {organization_id} has no memberships.")
        owner = next(
            (
                candidate
                for candidate in session.exec(
                    select(OrganizationUser).where(col(OrganizationUser.organization_id) == organization_id)
                )
                if candidate.role == OrganizationRole.OWNER
            ),
            membership,
        )

        template = session.exec(select(PlatformTemplate).order_by(col(PlatformTemplate.version).desc())).first()
        if template is None:
            raise SystemExit("No Platform Templates. Start the API once so it seeds them, then re-run.")

        for key, name in DEMO_AGENT_NAMES.items():
            existing = session.exec(
                select(Agent).where(
                    col(Agent.organization_id) == organization_id,
                    col(Agent.name) == name,
                    col(Agent.deleted_at).is_(None),
                )
            ).first()
            if existing is not None:
                pairs.append((existing, PERSONAS[key]))
                continue
            agent = Agent(
                organization_id=organization_id,
                created_by_user_id=owner.user_id,
                name=name,
                status=AgentStatus.STOPPED,
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
            session.flush()
            pairs.append((agent, PERSONAS[key]))
            print(f"Created demo Agent: {agent.name} ({agent.id})")
        session.commit()
        # Re-read: commit expired the instances, and they detach when this closes.
        for agent, _persona in pairs:
            session.refresh(agent)
        return pairs


def _organization_names(delegate: PostgresRepositoryDelegate) -> dict[uuid.UUID, str]:
    with Session(delegate.engine) as session:
        return {org.id: org.name for org in session.exec(select(Organization))}


def clear(delegate: PostgresRepositoryDelegate) -> None:
    """Remove every row a previous run wrote, and nothing else."""
    with Session(delegate.engine) as session:
        messages = session.exec(
            delete(AgentChatMessage).where(  # type: ignore[arg-type]
                col(AgentChatMessage.openclaw_msg_id).like(f"{MESSAGE_ID_PREFIX}-%")
            )
        )
        costs = session.exec(
            delete(CostRecord).where(col(CostRecord.request_id).like(f"{REQUEST_ID_PREFIX}-%"))  # type: ignore[arg-type]
        )
        session.commit()
    print(f"Cleared {costs.rowcount} seeded cost record(s) and {messages.rowcount} seeded message(s).")


def list_agents(delegate: PostgresRepositoryDelegate) -> None:
    org_names = _organization_names(delegate)
    with Session(delegate.engine) as session:
        agents = list(session.exec(select(Agent).where(col(Agent.deleted_at).is_(None))))
    if not agents:
        print("No Agents in this database. Create one in the UI first — this script never invents them.")
        return
    print(f"{len(agents)} Agent(s):\n")
    for agent in agents:
        print(f"  {agent.id}  {agent.name:<28}  {org_names.get(agent.organization_id, '?')}")


def seed(
    *,
    agent_ids: list[uuid.UUID],
    organization_id: uuid.UUID | None,
    persona_key: str | None,
    days: int,
    limit: int,
    seed_value: int | None,
    create_agents: bool,
) -> None:
    rng = random.Random(seed_value)
    delegate = PostgresRepositoryDelegate(get_config())
    encryption_key = get_config().agent_token_encryption_key

    if create_agents:
        targets = _ensure_demo_agents(delegate, organization_id)
    else:
        agents = _target_agents(delegate, agent_ids, organization_id, limit)
        if not agents:
            print("No matching Agents. Run with --list-agents to see what this database has.")
            delegate.close()
            return
        targets = [
            (agent, PERSONAS[persona_key or DEFAULT_ROTATION[index % len(DEFAULT_ROTATION)]])
            for index, agent in enumerate(agents)
        ]

    org_names = _organization_names(delegate)
    connections: dict[uuid.UUID, uuid.UUID] = {}
    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)

    records: list[CostRecord] = []
    messages: list[AgentChatMessage] = []
    report: list[tuple[Agent, Persona, int, int]] = []

    for agent, persona in targets:
        key_hash = _key_hash_for(agent, encryption_key)
        organization_name = org_names.get(agent.organization_id)
        connection_id = _connection_for(delegate, agent, connections) if persona.user_driven else None

        wakes = _wake_starts(persona, window_start, now, rng)
        agent_calls = 0
        for started_at in wakes:
            burst = _build_wake(
                agent=agent,
                organization_name=organization_name,
                persona=persona,
                started_at=started_at,
                key_hash=key_hash,
                rng=rng,
            )
            records.extend(burst)
            agent_calls += len(burst)
            if connection_id is not None:
                messages.extend(
                    _build_messages(
                        agent=agent,
                        connection_id=connection_id,
                        started_at=burst[0].occurred_at,
                        ended_at=burst[-1].occurred_at,
                        rng=rng,
                    )
                )
        report.append((agent, persona, len(wakes), agent_calls))

    # Summarise before the write: committing expires the instances.
    total_spend = sum((record.spend for record in records), Decimal(0))

    with Session(delegate.engine) as session:
        session.add_all(records)
        session.add_all(messages)
        session.commit()

    print(f"\nSeeded {len(records)} call(s) and {len(messages)} message(s) over {days} day(s).\n")
    for agent, persona, wakes, calls in report:
        print(f"  {agent.name}")
        print(f"    persona  {persona.key} — {persona.headline}")
        print(f"    {wakes} wake(s), {calls} call(s), {'user-triggered' if persona.user_driven else 'background'}")
        print(f"    open:    /dashboard/{agent.organization_id}/agents/{agent.id}?tab=activity\n")
    print(f"Total recorded spend ${total_spend:.2f}.")
    delegate.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent-id", action="append", default=[], help="Target this Agent (repeatable)")
    parser.add_argument("--organization-id", default=None, help="Target Agents in this Organization")
    parser.add_argument(
        "--persona",
        choices=sorted(PERSONAS),
        default=None,
        help="Give every target Agent this persona instead of rotating through them",
    )
    parser.add_argument("--days", type=int, default=7, help="How far back to generate (default: 7)")
    parser.add_argument("--limit", type=int, default=4, help="How many Agents to seed when none are named (default: 4)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output")
    parser.add_argument("--clear", action="store_true", help="Remove previously seeded rows, then seed again")
    parser.add_argument("--clear-only", action="store_true", help="Remove previously seeded rows and stop")
    parser.add_argument("--list-agents", action="store_true", help="Print the Agents in this database and stop")
    parser.add_argument(
        "--create-agents",
        action="store_true",
        help="Create one stopped demo Agent per persona first, so all four can be compared side by side",
    )
    args = parser.parse_args()

    if args.list_agents:
        delegate = PostgresRepositoryDelegate(get_config())
        list_agents(delegate)
        delegate.close()
        return

    if args.clear or args.clear_only:
        delegate = PostgresRepositoryDelegate(get_config())
        clear(delegate)
        delegate.close()
        if args.clear_only:
            return

    seed(
        agent_ids=[uuid.UUID(value) for value in args.agent_id],
        organization_id=uuid.UUID(args.organization_id) if args.organization_id else None,
        persona_key=args.persona,
        days=args.days,
        limit=args.limit,
        seed_value=args.seed,
        create_agents=args.create_agents,
    )


if __name__ == "__main__":
    main()
