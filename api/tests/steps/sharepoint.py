"""Steps for SharePoint signed in on an agent's Teams app, with Microsoft faked out."""

from dataclasses import dataclass, field
from uuid import UUID

import jwt
from fastapi import status
from injector import Module, provider, singleton
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.agents.microsoft_identity import MicrosoftIdentityClient, MicrosoftIdentityError, MicrosoftTokens
from api.domains.agents.models import AgentSecret, SecretProvider
from api.domains.agents.sharepoint_service import SignInState, encode_sign_in_state
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

TEAMS_APP_ID = "11111111-1111-4111-8111-111111111111"
TEAMS_TENANT_ID = "22222222-2222-4222-8222-222222222222"
TEAMS_APP_PASSWORD = "bot-secret"
SIGNED_IN_EMAIL = "someone@contoso.com"
CODE_VERIFIER = "the-pkce-verifier-" + "v" * 40


def id_token(tenant_id: str = TEAMS_TENANT_ID, email: str = SIGNED_IN_EMAIL) -> str:
    return jwt.encode({"tid": tenant_id, "preferred_username": email}, "id-token-test-key-" * 2, algorithm="HS256")


def tokens(
    *,
    refresh_token: str | None = "rt-from-exchange",
    scope: str = "https://graph.microsoft.com/Sites.ReadWrite.All",
    tenant_id: str = TEAMS_TENANT_ID,
    email: str = SIGNED_IN_EMAIL,
) -> MicrosoftTokens:
    return MicrosoftTokens(
        access_token="at-from-exchange",
        refresh_token=refresh_token,
        expires_in=3600,
        scope=scope,
        id_token=id_token(tenant_id=tenant_id, email=email),
    )


@dataclass
class FakeMicrosoftIdentity(MicrosoftIdentityClient):
    """Stands in for Microsoft's token endpoint and records what it was asked."""

    exchange_result: MicrosoftTokens | Exception = field(default_factory=tokens)
    exchanges: list[dict] = field(default_factory=list)

    def exchange_code(self, **kwargs) -> MicrosoftTokens:
        self.exchanges.append(kwargs)
        if isinstance(self.exchange_result, Exception):
            raise self.exchange_result
        return self.exchange_result


class FakeMicrosoftIdentityModule(Module):
    @provider
    @singleton
    def provide_identity(self) -> MicrosoftIdentityClient:
        return FakeMicrosoftIdentity()


def public_client_flows_off() -> MicrosoftIdentityError:
    return MicrosoftIdentityError(
        "invalid_client",
        "AADSTS7000218: The request body must contain the following parameter: 'client_assertion' or 'client_secret'.",
    )


def fake_identity(context) -> FakeMicrosoftIdentity:
    identity = context.injector.get(MicrosoftIdentityClient)
    assert isinstance(identity, FakeMicrosoftIdentity)
    return identity


def auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def agent_base(context) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"


def there_is_a_teams_connection(enabled: bool = True, tenant_id: str = TEAMS_TENANT_ID):
    def step(context):
        response = context.client.post(
            f"{agent_base(context)}/connections",
            json={
                "platform_key": "teams",
                "display_name": "Microsoft Teams",
                "credentials": {
                    "app_id": TEAMS_APP_ID,
                    "app_password": TEAMS_APP_PASSWORD,
                    "tenant_id": tenant_id,
                },
            },
            headers=auth(context),
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        context.teams_connection = response.json()
        if not enabled:
            disabled = context.client.patch(
                f"{agent_base(context)}/connections/{context.teams_connection['id']}",
                json={"enabled": False, "revision": context.teams_connection["revision"]},
                headers=auth(context),
            )
            assert disabled.status_code == status.HTTP_200_OK, disabled.text

    return step


def sign_in_state(context, *, read_only: bool = False, user_id: UUID | None = None) -> str:
    config = context.injector.get(Config)
    return encode_sign_in_state(
        config,
        SignInState(
            agent_id=context.agent.id,
            connection_id=UUID(context.teams_connection["id"]),
            user_id=user_id or context.user.id,
            read_only=read_only,
            code_verifier=CODE_VERIFIER,
        ),
    )


def sign_in(context, *, read_only: bool = False, user_id: UUID | None = None):
    return context.client.post(
        f"{agent_base(context)}/integrations/sharepoint/sign-in",
        json={"code": "the-code", "state": sign_in_state(context, read_only=read_only, user_id=user_id)},
        headers=auth(context),
    )


def sharepoint_is_signed_in():
    def step(context):
        response = sign_in(context)
        assert response.status_code == status.HTTP_200_OK, response.text

    return step


def sharepoint_secret(context) -> AgentSecret | None:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return session.exec(
            select(AgentSecret)
            .where(col(AgentSecret.agent_id) == context.agent.id)
            .where(col(AgentSecret.provider) == SecretProvider.SHAREPOINT)
        ).first()
