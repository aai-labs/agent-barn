"""Seed stopped local Agents for manually exercising Agent configuration overrides.

This is a local-development fixture, not production bootstrap data. It creates
three headless Agents, so opening the Agent UI does not call an external
communication platform or start a workload. Re-running the command
is idempotent by organization and fixture name.

Usage (from the repository root)::

    api/.venv/bin/python -m api.scripts.seed_agent_override_fixtures \
        --organization-id 019fe78b-4c04-747c-b8d0-b6808b3034a9
"""

from __future__ import annotations

import argparse
from uuid import UUID

from sqlmodel import Session, col, select

from api.core.config import get_config
from api.domains.agents.models import (
    Agent,
    AgentAccess,
    AgentStatus,
    AgentType,
)
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID
from api.domains.rbac.models import AgentAccessRole
from api.domains.templates.models import PlatformTemplate
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

DEFAULT_FIXTURE_PREFIX = "Override Playground"
TEMPLATE_KEYS = ("general-purpose", "email-reminder")


def _latest_templates(session: Session, template_keys: tuple[str, ...]) -> dict[str, PlatformTemplate]:
    rows = session.exec(
        select(PlatformTemplate)
        .where(col(PlatformTemplate.template_key).in_(template_keys))
        .order_by(col(PlatformTemplate.template_key), col(PlatformTemplate.version).desc())
    ).all()
    latest: dict[str, PlatformTemplate] = {}
    for template in rows:
        latest.setdefault(template.template_key, template)
    return latest


def seed_agents(organization_id: UUID, count: int, prefix: str) -> None:
    if count < 1:
        raise ValueError("count must be at least 1")

    config = get_config()
    delegate = PostgresRepositoryDelegate(config)
    try:
        with Session(delegate.engine) as session:
            organization = session.get(Organization, organization_id)
            if organization is None:
                raise ValueError(f"Organization {organization_id} was not found")

            memberships = list(
                session.exec(
                    select(OrganizationUser)
                    .where(col(OrganizationUser.organization_id) == organization_id)
                    .order_by(col(OrganizationUser.created_at))
                ).all()
            )
            if not memberships:
                raise ValueError(f"Organization {organization_id} has no memberships")
            if session.get(AgentAccessRole, AGENT_OWNER_ROLE_ID) is None:
                raise ValueError("The system Agent Owner role has not been seeded")

            owner_membership = next(
                (membership for membership in memberships if membership.role == OrganizationRole.OWNER),
                memberships[0],
            )
            creator = session.get(User, owner_membership.user_id) if owner_membership.user_id else None
            templates = _latest_templates(session, TEMPLATE_KEYS)
            missing_templates = [key for key in TEMPLATE_KEYS if key not in templates]
            if missing_templates:
                missing = ", ".join(missing_templates)
                raise ValueError(f"Missing predefined template(s): {missing}. Start the API once to seed them.")

            print(f"Organization: {organization.name} ({organization_id})")
            if creator is not None:
                print(f"Granting Agent Owner access to: {creator.email}")

            created = 0
            skipped = 0
            for index in range(1, count + 1):
                name = f"{prefix} {index}"
                existing = session.exec(
                    select(Agent).where(
                        col(Agent.organization_id) == organization_id,
                        col(Agent.name) == name,
                        col(Agent.deleted_at).is_(None),
                    )
                ).first()
                if existing is not None:
                    print(f"Already exists: {existing.name} ({existing.id})")
                    skipped += 1
                    continue

                template_key = TEMPLATE_KEYS[(index - 1) % len(TEMPLATE_KEYS)]
                template = templates[template_key]
                agent = Agent(
                    organization_id=organization_id,
                    created_by_user_id=owner_membership.user_id,
                    name=name,
                    status=AgentStatus.STOPPED,
                    agent_type=AgentType.OPENCLAW,
                    platform_template_id=template.id,
                    model=config.agent_default_model,
                )
                access = AgentAccess(
                    organization_id=organization_id,
                    membership_id=owner_membership.id,
                    agent_id=agent.id,
                    access_role_id=AGENT_OWNER_ROLE_ID,
                )
                session.add_all([agent, access])
                session.flush()
                print(f"Created: {agent.name} ({agent.id}) — {template_key} v{template.version}")
                created += 1

            session.commit()
            print(f"Seed complete: {created} created, {skipped} already present.")
    finally:
        delegate.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True, type=UUID)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--prefix", default=DEFAULT_FIXTURE_PREFIX)
    args = parser.parse_args()
    seed_agents(args.organization_id, args.count, args.prefix)


if __name__ == "__main__":
    main()
