import datetime
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.models import GatewayToken
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class GatewayTokenRepository:
    delegate: PostgresRepositoryDelegate

    def find_active_by_hash(self, token_hash: str) -> GatewayToken | None:
        """Resolve a presented token. Indexed on ``token_hash``; the hot path."""
        with Session(self.delegate.engine) as session:
            query = (
                select(GatewayToken)
                .where(col(GatewayToken.token_hash) == token_hash)
                .where(col(GatewayToken.revoked_at).is_(None))
            )
            return _with_provider_enum(session.exec(query).first())

    def find_active_for_agent(self, agent_id: UUID) -> list[GatewayToken]:
        with Session(self.delegate.engine) as session:
            query = (
                select(GatewayToken)
                .where(col(GatewayToken.agent_id) == agent_id)
                .where(col(GatewayToken.revoked_at).is_(None))
            )
            return [t for t in (_with_provider_enum(t) for t in session.exec(query).all()) if t is not None]

    def save(self, token: GatewayToken) -> GatewayToken:
        self.delegate.save(token)
        return token

    def revoke_for_agent(
        self,
        agent_id: UUID,
        *,
        providers: set[SecretProvider] | None = None,
        now: datetime.datetime | None = None,
    ) -> int:
        """Revoke an Agent's live tokens, optionally narrowed to some providers.

        Returns the number revoked. Revoking is a stamp rather than a delete so the
        audit trail survives the credential it authorized.
        """
        revoked_at = now or datetime.datetime.now(datetime.UTC)
        with Session(self.delegate.engine) as session:
            query = (
                select(GatewayToken)
                .where(col(GatewayToken.agent_id) == agent_id)
                .where(col(GatewayToken.revoked_at).is_(None))
            )
            if providers is not None:
                query = query.where(col(GatewayToken.provider).in_(providers))
            tokens = list(session.exec(query).all())
            for token in tokens:
                token.revoked_at = revoked_at
                session.add(token)
            session.commit()
            return len(tokens)

    def touch_last_used(self, token_id: UUID, when: datetime.datetime) -> None:
        """Best-effort usage stamp. Never gates authorization."""
        with Session(self.delegate.engine) as session:
            token = session.get(GatewayToken, token_id)
            if token is None:
                return
            token.last_used_at = when
            session.add(token)
            session.commit()


def _with_provider_enum(token: GatewayToken | None) -> GatewayToken | None:
    """Coerce the stored provider string back to its enum member.

    The column is a plain ``String`` (matching ``agent_secret.provider``), so SQLModel
    hands back the raw value on read. Coercing here keeps every caller — audit sink
    included — working with the enum rather than re-deriving it.
    """
    if token is not None:
        token.provider = SecretProvider(token.provider)
    return token
