"""Local dev fixture generator for the Cost pages (AF-281).

Not part of the production/test code path. Writes realistic ``cost_record`` rows so
the org and platform cost pages have something to browse before the sync job exists.
Safe to re-run; each run adds another batch on top of whatever already exists.

The shape of the data deliberately mirrors what production actually looks like:

* A **cutover date** splits the timeline. Calls before it were streamed through a
  LiteLLM version that dropped OpenRouter's cost, so they sit at ``spend = 0`` with
  real token counts — these are the healing job's candidates.
* Some of those have already been healed, so they carry ``openrouter_backfill`` and a
  ``healed_at``. A sync pass must never revert them.
* Failed calls also record ``spend = 0``, but with a UUID request id instead of an
  OpenRouter generation id. They are **not** healable, and mistaking them for
  candidates is how failed requests acquire fabricated spend.
* A small slice has no agent attribution at all — the unattributed bucket the
  platform page surfaces.

Real Agents in the local database are used where they exist, keyed by the SHA-256 of
their decrypted LiteLLM key exactly as the sync job will key them. The rest are
invented: ``cost_record`` carries no foreign keys, so rows for agents that no longer
exist are a normal, expected state rather than a broken one.

Usage (from the repo root, with the dev stack's Postgres reachable):
    make seed-costs
    uv run --project api python -m api.scripts.seed_cost_fixtures --count 4000
"""

import argparse
import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from api.core.config import get_config
from api.domains.agents.models import Agent
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.organizations.models import Organization
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# The day production moved to a LiteLLM build that keeps OpenRouter's reported cost
# on streamed responses. Calls before it recorded tokens but no money.
COST_CUTOVER = datetime(2026, 8, 17, 19, 31, tzinfo=UTC)

ORG_NAMES = [
    "Acme Robotics",
    "Globex Corporation",
    "Initech",
    "Umbrella Labs",
    "Stark Industries",
]

AGENT_NAMES = [
    "Support Bot",
    "Release Notes Agent",
    "Standup Reporter",
    "Incident Triager",
    "Onboarding Guide",
    "Sales Researcher",
    "Docs Librarian",
]

# (model, weight, mean $ per call). Prices are the right order of magnitude for each
# tier so the cost-per-call histogram has a believable long tail.
WEIGHTED_MODELS = [
    ("openrouter/z-ai/glm-5.2", 30, 0.0182),
    ("openrouter/anthropic/claude-sonnet-5", 22, 0.0413),
    ("openrouter/anthropic/claude-opus-5", 6, 0.2140),
    ("openrouter/openai/gpt-5-mini", 18, 0.0031),
    ("openrouter/google/gemini-3.6-flash", 14, 0.0009),
    ("openrouter/deepseek/deepseek-chat", 10, 0.0044),
]

CALL_TYPES = ["acompletion", "completion", "aembedding"]

# Share of generated rows, by kind.
FAILURE_RATE = 0.04
UNATTRIBUTED_RATE = 0.01
ALREADY_HEALED_RATE = 0.35  # of the pre-cutover zero-spend rows


def _get_or_create_organizations(delegate: PostgresRepositoryDelegate) -> list[Organization]:
    """Reuse whatever orgs the local database already has, topping up to a useful spread."""
    with Session(delegate.engine) as session:
        existing = list(session.exec(select(Organization)))
    if len(existing) >= 4:
        return existing
    existing_names = {org.name for org in existing}
    organizations = list(existing)
    for name in ORG_NAMES:
        if name in existing_names:
            continue
        org = Organization(name=name, description=f"{name} — seeded for local cost page testing")
        delegate.save(org)
        organizations.append(org)
    return organizations


def _real_agents(delegate: PostgresRepositoryDelegate) -> list[Agent]:
    with Session(delegate.engine) as session:
        return list(session.exec(select(Agent)))


def _key_hash_for(agent: Agent, encryption_key: str) -> str:
    """SHA-256 of the agent's LiteLLM key — the same join key the sync job builds."""
    try:
        return hashlib.sha256(decrypt_token(agent.litellm_key_encrypted, encryption_key).encode()).hexdigest()
    except Exception:
        # A key encrypted under a rotated secret is exactly the case that lands rows
        # in the unattributed bucket. Fall back to a stable synthetic hash.
        return hashlib.sha256(str(agent.id).encode()).hexdigest()


def _build_attribution_pool(
    delegate: PostgresRepositoryDelegate,
    organizations: list[Organization],
    rng: random.Random,
) -> list[dict]:
    """One entry per (agent, org) pair a cost row can be attributed to."""
    config = get_config()
    encryption_key = config.agent_token_encryption_key
    orgs_by_id = {org.id: org for org in organizations}

    pool: list[dict] = []
    for agent in _real_agents(delegate):
        org = orgs_by_id.get(agent.organization_id)
        pool.append(
            {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "organization_id": agent.organization_id,
                "organization_name": org.name if org else None,
                "litellm_key_hash": _key_hash_for(agent, encryption_key),
            }
        )

    # Invented agents fill out the org filter and give the platform page more than two
    # rows to rank. These intentionally have no matching `agent` row: cost history is
    # meant to outlive the agents it describes.
    for org in organizations:
        for name in rng.sample(AGENT_NAMES, k=rng.randint(2, 4)):
            agent_id = uuid.uuid5(uuid.NAMESPACE_URL, f"af281-fixture/{org.id}/{name}")
            pool.append(
                {
                    "agent_id": agent_id,
                    "agent_name": name,
                    "organization_id": org.id,
                    "organization_name": org.name,
                    "litellm_key_hash": hashlib.sha256(str(agent_id).encode()).hexdigest(),
                }
            )
    return pool


def _pick_weighted(weighted: list[tuple], rng: random.Random):
    items = [item for item, *_rest in weighted]
    weights = [row[1] for row in weighted]
    return rng.choices(items, weights=weights, k=1)[0]


def _spend_for(mean: float, rng: random.Random) -> Decimal:
    """Long-tailed cost around the model's mean, so the histogram is not a single bar."""
    value = rng.lognormvariate(0.0, 0.85) * mean
    return Decimal(f"{value:.12f}")


def _build_record(
    *,
    occurred_at: datetime,
    attribution: dict | None,
    rng: random.Random,
) -> CostRecord:
    model = _pick_weighted([(name, weight) for name, weight, _mean in WEIGHTED_MODELS], rng)
    mean = next(m for name, _w, m in WEIGHTED_MODELS if name == model)

    prompt_tokens = rng.randint(300, 24_000)
    completion_tokens = rng.randint(20, 2_400)
    duration_ms = rng.randint(400, 42_000)
    failed = rng.random() < FAILURE_RATE

    if failed:
        # Failures record a UUID request id, not an OpenRouter generation id. There is
        # no generation to look up and no money to recover.
        return CostRecord(
            request_id=str(uuid.uuid4()),
            litellm_key_hash=attribution["litellm_key_hash"] if attribution else uuid.uuid4().hex,
            occurred_at=occurred_at,
            ended_at=occurred_at + timedelta(milliseconds=duration_ms),
            spend=Decimal(0),
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            total_tokens=prompt_tokens,
            model=model,
            status="failure",
            call_type=rng.choice(CALL_TYPES),
            request_duration_ms=duration_ms,
            agent_id=attribution["agent_id"] if attribution else None,
            organization_id=attribution["organization_id"] if attribution else None,
            agent_name=attribution["agent_name"] if attribution else None,
            organization_name=attribution["organization_name"] if attribution else None,
            source=CostRecordSource.LITELLM_LIVE,
        )

    true_spend = _spend_for(mean, rng)
    pre_cutover = occurred_at < COST_CUTOVER
    healed = pre_cutover and rng.random() < ALREADY_HEALED_RATE

    if pre_cutover and not healed:
        # The defect itself: real tokens, no recorded money, waiting to be healed.
        spend = Decimal(0)
        source = CostRecordSource.LITELLM_LIVE
        healed_at = None
    elif healed:
        spend = true_spend
        source = CostRecordSource.OPENROUTER_BACKFILL
        healed_at = COST_CUTOVER + timedelta(days=rng.uniform(0, 3))
    else:
        spend = true_spend
        source = CostRecordSource.LITELLM_LIVE
        healed_at = None

    return CostRecord(
        request_id=f"gen-{int(occurred_at.timestamp())}-{uuid.uuid4().hex[:16]}",
        litellm_key_hash=attribution["litellm_key_hash"] if attribution else uuid.uuid4().hex,
        occurred_at=occurred_at,
        ended_at=occurred_at + timedelta(milliseconds=duration_ms),
        spend=spend,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=model,
        status="success",
        call_type=rng.choice(CALL_TYPES),
        request_duration_ms=duration_ms,
        agent_id=attribution["agent_id"] if attribution else None,
        organization_id=attribution["organization_id"] if attribution else None,
        agent_name=attribution["agent_name"] if attribution else None,
        organization_name=attribution["organization_name"] if attribution else None,
        source=source,
        healed_at=healed_at,
    )


def seed(count: int, days: int, seed_value: int | None) -> None:
    rng = random.Random(seed_value)
    delegate = PostgresRepositoryDelegate(get_config())

    organizations = _get_or_create_organizations(delegate)
    pool = _build_attribution_pool(delegate, organizations, rng)
    print(f"Using {len(organizations)} Organization(s) and {len(pool)} Agent attribution(s).")

    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)

    records: list[CostRecord] = []
    for _ in range(count):
        # Weight recent traffic higher, the way real usage grows.
        offset = rng.random() ** 0.7
        occurred_at = window_start + (now - window_start) * offset
        attribution = None if rng.random() < UNATTRIBUTED_RATE else rng.choice(pool)
        records.append(_build_record(occurred_at=occurred_at, attribution=attribution, rng=rng))

    # Summarise before the write: committing expires the instances, and they detach
    # when the Session closes.
    healable = sum(
        1 for r in records if r.spend == 0 and r.status == "success" and r.source == CostRecordSource.LITELLM_LIVE
    )
    healed = sum(1 for r in records if r.source == CostRecordSource.OPENROUTER_BACKFILL)
    failures = sum(1 for r in records if r.status == "failure")
    unattributed = sum(1 for r in records if r.agent_id is None)
    total = sum((r.spend for r in records), Decimal(0))

    with Session(delegate.engine) as session:
        session.add_all(records)
        session.commit()

    print(
        f"Seeded {len(records)} cost records over {days} days: "
        f"{healable} awaiting healing, {healed} already healed, "
        f"{failures} failures (not healable), {unattributed} unattributed. "
        f"Recorded spend ${total:.6f}."
    )
    delegate.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=4000, help="Number of cost records to write (default: 4000)")
    parser.add_argument("--days", type=int, default=45, help="How far back to spread them (default: 45)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output")
    args = parser.parse_args()
    seed(args.count, args.days, args.seed)


if __name__ == "__main__":
    main()
