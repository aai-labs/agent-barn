"""Shared steps for the Agent Add-on integration tests: personas, requests and decisions."""

from uuid import UUID, uuid7

from api.domains.agent_addons.models import AgentAddon
from api.domains.events.models import DomainEventEnvelope, OutboxMessage
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.modules import set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_agent_access
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

AGENTS = "/api/v1/organizations/{organization_id}/agents"
PLATFORM_ADDONS = "/api/v1/platform/agent-addons"

ADDON_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        "API_EXTERNAL_URL": "https://api.test.com",
        "SKIP_SLACK_TOKEN_VALIDATION": "true",
        "WEB_APP_URL": "https://app.test.com",
        # Email delivery on, so the notification handler sends; the client is faked per test.
        "CLOUDFLARE_ACCOUNT_ID": "account",
        "CLOUDFLARE_API_TOKEN": "token",
        "SENDER_EMAIL": "noreply@test.com",
    }
)

HUMANIZE = {
    "kind": "pip",
    "name": "humanize",
    "version": "1.2.0",
    "reason": "Formats numbers and dates in reports.",
}


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def delegate(context) -> PostgresRepositoryDelegate:
    return context.injector.get(PostgresRepositoryDelegate)


def _keeping_actor(context, make):
    """Run `make` without replacing the test's Owner as the context's actor."""
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    try:
        return make()
    finally:
        for name, value in saved.items():
            setattr(context, name, value)


def member(
    context, role: OrganizationRole, *, email_verified: bool = True, organization_id: UUID | None = None
) -> tuple[str, OrganizationUser]:
    """A Membership's token and the Membership."""

    def make():
        user_id = uuid7()
        there_is_a_user(
            id=user_id,
            name=f"{role.value.title()} {user_id.hex[-4:]}",
            email=f"{role.value.lower()}-{user_id}@example.com",
            role=role,
            organization_id=organization_id or context.organization.id,
            email_verified=email_verified,
        )(context)
        membership = context.organization_user
        there_is_an_access_token_for_user(user_id)(context)
        return context.access_token, membership

    return _keeping_actor(context, make)


def platform_admin(context, *, email: str | None = None) -> str:
    def make():
        context.organization = None
        admin_id = uuid7()
        there_is_a_user(
            id=admin_id,
            name="Platform Admin",
            email=email or f"platform-{admin_id}@example.com",
            is_platform_admin=True,
        )(context)
        there_is_an_access_token_for_user(admin_id)(context)
        return context.access_token

    return _keeping_actor(context, make)


def owner(context) -> str:
    return context.access_token


def admin(context) -> str:
    return member(context, OrganizationRole.ADMIN)[0]


def with_agent_role(role_id):
    def persona(context) -> str:
        token, membership = member(context, OrganizationRole.MEMBER)
        there_is_agent_access(membership_id=membership.id, access_role_id=role_id)(context)
        return token

    return persona


def unassigned_member(context) -> str:
    return member(context, OrganizationRole.MEMBER)[0]


def pending_member(context) -> str:
    return member(context, OrganizationRole.MEMBER, email_verified=False)[0]


def read_only_key(context, token: str) -> str:
    response = context.client.post(
        "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(token)
    )
    return response.json()["token"]


def addons_url(context, agent_id: UUID | None = None) -> str:
    return f"{AGENTS}/{agent_id or context.agent.id}/addons"


def request_addon(context, token: str, body: dict | None = None, agent_id: UUID | None = None):
    return context.client.post(addons_url(context, agent_id), json=body or HUMANIZE, headers=auth(token))


def list_addons(context, token: str, agent_id: UUID | None = None):
    return context.client.get(addons_url(context, agent_id), headers=auth(token))


def withdraw_addon(context, token: str, addon_id, agent_id: UUID | None = None):
    return context.client.post(f"{addons_url(context, agent_id)}/{addon_id}/withdraw", headers=auth(token))


def decide(context, token: str, addon_id, action: str, reason: str | None = None):
    return context.client.post(
        f"{PLATFORM_ADDONS}/{addon_id}/{action}",
        json={"reason": reason} if action == "reject" else None,
        headers=auth(token),
    )


def an_approved_addon(context, admin_token: str, body: dict | None = None) -> str:
    addon_id = request_addon(context, context.access_token, body).json()["id"]
    decide(context, admin_token, addon_id, "approve")
    return addon_id


def stored_addon(context, addon_id) -> AgentAddon:
    addon = delegate(context).find_by_id(AgentAddon, UUID(str(addon_id)))
    assert addon is not None
    return addon


def events(context, *names: str) -> list[OutboxMessage]:
    return sorted(
        (message for message in delegate(context).find_all(OutboxMessage) if message.event_name in names),
        key=lambda message: message.occurred_at,
    )


def envelope(message: OutboxMessage) -> DomainEventEnvelope:
    return EventDeliveryProcessor._envelope_from_message(message)
