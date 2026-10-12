"""Steps for SharePoint signed in on an agent's Teams app, with Microsoft faked out."""

from dataclasses import dataclass, field
from uuid import UUID

import jwt
from fastapi import status
from injector import Module, provider, singleton
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.agents.microsoft_graph_sites import MicrosoftGraphSites, SiteNotFound
from api.domains.agents.microsoft_identity import MicrosoftIdentityClient, MicrosoftIdentityError, MicrosoftTokens
from api.domains.agents.models import AgentSecret, SecretProvider, SharePointContent, encrypt_content
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
    app_token_result: MicrosoftTokens | Exception = field(default_factory=lambda: app_tokens())
    app_token_requests: list[dict] = field(default_factory=list)

    def exchange_code(self, **kwargs) -> MicrosoftTokens:
        self.exchanges.append(kwargs)
        if isinstance(self.exchange_result, Exception):
            raise self.exchange_result
        return self.exchange_result

    def client_credentials(self, **kwargs) -> MicrosoftTokens:
        self.app_token_requests.append(kwargs)
        if isinstance(self.app_token_result, Exception):
            raise self.app_token_result
        return self.app_token_result


def app_tokens(access_token: str = "app-only-token", expires_in: int = 3599) -> MicrosoftTokens:
    return MicrosoftTokens(
        access_token=access_token, refresh_token=None, expires_in=expires_in, scope="", id_token=None
    )


ADMIN_EMAIL = "admin@contoso.com"
SITE_GRANT_SCOPE = "https://graph.microsoft.com/Sites.FullControl.All"


def admin_tokens(*, scope: str = SITE_GRANT_SCOPE, tenant_id: str = TEAMS_TENANT_ID) -> MicrosoftTokens:
    """What the administrator's grant sign-in returns: no refresh token, since it asks for none."""
    return MicrosoftTokens(
        access_token="admin-access-token",
        refresh_token=None,
        expires_in=3600,
        scope=scope,
        id_token=id_token(tenant_id=tenant_id, email=ADMIN_EMAIL),
    )


def site_id_for(url: str) -> str:
    return f"id:{url}"


@dataclass
class FakeMicrosoftGraphSites(MicrosoftGraphSites):
    """Stands in for Graph's site permission API and records what it was asked."""

    unknown_sites: set[str] = field(default_factory=set)
    # Raised by the grant (or revoke) of the named site.
    grant_failures: dict[str, Exception] = field(default_factory=dict)
    revoke_failures: dict[str, Exception] = field(default_factory=dict)
    grants: list[dict] = field(default_factory=list)
    revokes: list[dict] = field(default_factory=list)
    role_updates: list[dict] = field(default_factory=list)

    def resolve_site_id(self, token: str, site_url: str) -> str:
        if site_url in self.unknown_sites:
            raise SiteNotFound(site_url)
        return site_id_for(site_url)

    def grant_site(self, token: str, *, site_id: str, app_id: str, display_name: str, role: str) -> str:
        if site_id in self.grant_failures:
            raise self.grant_failures[site_id]
        self.grants.append({"token": token, "site_id": site_id, "app_id": app_id, "role": role})
        return f"perm-{len(self.grants)}"

    def update_site_role(self, token: str, *, site_id: str, permission_id: str, role: str) -> None:
        self.role_updates.append({"site_id": site_id, "permission_id": permission_id, "role": role})

    def revoke_site(self, token: str, *, site_id: str, permission_id: str) -> None:
        if site_id in self.revoke_failures:
            raise self.revoke_failures[site_id]
        self.revokes.append({"token": token, "site_id": site_id, "permission_id": permission_id})


class FakeMicrosoftIdentityModule(Module):
    @provider
    @singleton
    def provide_identity(self) -> MicrosoftIdentityClient:
        return FakeMicrosoftIdentity()

    @provider
    @singleton
    def provide_graph_sites(self) -> MicrosoftGraphSites:
        return FakeMicrosoftGraphSites()


def public_client_flows_off() -> MicrosoftIdentityError:
    return MicrosoftIdentityError(
        "invalid_client",
        "AADSTS7000218: The request body must contain the following parameter: 'client_assertion' or 'client_secret'.",
    )


def fake_identity(context) -> FakeMicrosoftIdentity:
    identity = context.injector.get(MicrosoftIdentityClient)
    assert isinstance(identity, FakeMicrosoftIdentity)
    return identity


def fake_graph_sites(context) -> FakeMicrosoftGraphSites:
    sites = context.injector.get(MicrosoftGraphSites)
    assert isinstance(sites, FakeMicrosoftGraphSites)
    return sites


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


def sign_in_state(
    context,
    *,
    read_only: bool = False,
    user_id: UUID | None = None,
    sites: tuple[str, ...] | None = None,
    remove_all: bool = False,
) -> str:
    config = context.injector.get(Config)
    return encode_sign_in_state(
        config,
        SignInState(
            agent_id=context.agent.id,
            connection_id=UUID(context.teams_connection["id"]),
            user_id=user_id or context.user.id,
            read_only=read_only,
            code_verifier=CODE_VERIFIER,
            mode="selected_sites" if sites is not None or remove_all else "delegated",
            sites=sites or (),
            remove_all=remove_all,
        ),
    )


def sign_in(
    context,
    *,
    read_only: bool = False,
    user_id: UUID | None = None,
    sites: tuple[str, ...] | None = None,
    remove_all: bool = False,
):
    """Complete a sign-in; passing ``sites`` makes it the administrator's selected-sites grant, and
    ``remove_all`` the administrator's sign-in that takes every site away."""
    state = sign_in_state(context, read_only=read_only, user_id=user_id, sites=sites, remove_all=remove_all)
    return context.client.post(
        f"{agent_base(context)}/integrations/sharepoint/sign-in",
        json={"code": "the-code", "state": state},
        headers=auth(context),
    )


def sites_are_granted(*sites: str, read_only: bool = False):
    """An administrator has granted the agent's Teams app these sites."""

    def step(context):
        identity = fake_identity(context)
        previous = identity.exchange_result
        identity.exchange_result = admin_tokens()
        try:
            response = sign_in(context, read_only=read_only, sites=sites)
        finally:
            identity.exchange_result = previous
        assert response.status_code == status.HTTP_200_OK, response.text

    return step


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


def replace_sharepoint_content(context, content: SharePointContent) -> None:
    """Overwrite the stored credential, as if it had been saved in an earlier state."""
    delegate = context.injector.get(PostgresRepositoryDelegate)
    config = context.injector.get(Config)
    with Session(delegate.engine) as session:
        secret = session.exec(
            select(AgentSecret)
            .where(col(AgentSecret.agent_id) == context.agent.id)
            .where(col(AgentSecret.provider) == SecretProvider.SHAREPOINT)
        ).one()
        secret.content = encrypt_content(content, config.agent_token_encryption_key)
        session.add(secret)
        session.commit()
