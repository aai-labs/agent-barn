import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, ClassVar
from uuid import UUID, uuid5

from injector import inject, singleton

from api.core.config import Config
from api.domains.analytics.repository import InstallationRepository
from api.domains.events.catalog import (
    AGENT_CREATED,
    AGENT_DELETED,
    AGENT_STARTED,
    AGENT_STOPPED,
    AGENT_UPDATED,
    ORGANIZATION_CREATED,
    ORGANIZATION_DELETED,
    ORGANIZATION_MEMBER_ADDED,
    ORGANIZATION_MEMBER_REMOVED,
    ORGANIZATION_OWNERSHIP_TRANSFERRED,
    ORGANIZATION_ROLE_CHANGED,
    ORGANIZATION_UPDATED,
    PRODUCT_ANALYTICS_HANDLER,
    USER_LOGGED_IN,
    USER_SIGNED_UP,
)
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import ActorIdentityType, DomainEventEnvelope
from api.domains.users.models import User
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.posthog.client import PostHogClient
from api.infrastructure.posthog.exceptions import RetryablePostHogException, TerminalPostHogException

logger = logging.getLogger(__name__)

SOURCE = "agentbarn-api"
MAX_DELIVERY_ATTEMPTS = 3
INSTALLATION_GROUP = "installation"
ORGANIZATION_GROUP = "organization"
_AGENT_LIFECYCLE_FIELDS = ("agent_id", "runtime", "previous_status", "new_status")
_EVENT_FIELDS: dict[str, tuple[str, ...]] = {
    AGENT_CREATED: ("agent_id", "runtime"),
    AGENT_UPDATED: ("agent_id",),
    AGENT_STARTED: _AGENT_LIFECYCLE_FIELDS,
    AGENT_STOPPED: _AGENT_LIFECYCLE_FIELDS,
    AGENT_DELETED: ("agent_id", "runtime"),
    ORGANIZATION_CREATED: (),
    ORGANIZATION_UPDATED: ("changed_fields",),
    ORGANIZATION_DELETED: (),
    USER_LOGGED_IN: ("method",),
    USER_SIGNED_UP: (),
    ORGANIZATION_MEMBER_ADDED: ("membership_id", "role"),
    ORGANIZATION_MEMBER_REMOVED: ("membership_id", "role"),
    ORGANIZATION_ROLE_CHANGED: ("membership_id", "previous_role", "new_role"),
    ORGANIZATION_OWNERSHIP_TRANSFERRED: ("previous_owner_membership_id", "new_owner_membership_id"),
}
_HUMAN_ACTORS = frozenset({ActorIdentityType.MEMBERSHIP, ActorIdentityType.USER})


def installation_name(config: Config, installation_id: UUID | str) -> str:
    return config.installation_display_name or str(installation_id)


def _as_uuid(value: object) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except ValueError:
        return None


@inject
@singleton
@dataclass
class ProductAnalyticsHandler:
    config: Config
    installation_repository: InstallationRepository
    organization_user_repository: OrganizationUserRepository
    user_repository: UserRepository
    posthog_client: PostHogClient
    _identified_installation_name: str | None = field(default=None, init=False)
    _installation_naming_lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    name: ClassVar[str] = PRODUCT_ANALYTICS_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = tuple(
        SupportedEvent(event_name, 1) for event_name in _EVENT_FIELDS
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if not self.config.is_analytics_enabled:
            return
        if event.actor.type not in _HUMAN_ACTORS:
            return
        user = self._resolve_user(event, event.organization_id)
        if user is None:
            logger.info(
                "Product analytics skipped: event_id=%s event_name=%s reason=actor_not_found",
                event.event_id,
                event.event_name,
            )
            return

        try:
            self._send_messages(event, user)
        except RetryablePostHogException as exc:
            if context.attempt_count < MAX_DELIVERY_ATTEMPTS:
                raise RetryableEventHandlerError(str(exc)) from exc
            logger.warning(
                "Product analytics dropped: event_id=%s event_name=%s attempt_count=%s error=%s",
                event.event_id,
                event.event_name,
                context.attempt_count,
                exc,
            )
        except TerminalPostHogException as exc:
            raise TerminalEventHandlerError(str(exc)) from exc

    def _send_messages(self, event: DomainEventEnvelope, user: User) -> None:
        # The singleton is shared by worker threads. Hold the lock through a
        # naming send so another delivery cannot name the same Installation too.
        with self._installation_naming_lock:
            name = installation_name(self.config, self.installation_repository.get_id())
            if name != self._identified_installation_name:
                self.posthog_client.send_batch(self._messages(event, event.organization_id, user, identify=True))
                self._identified_installation_name = name
                return
        self.posthog_client.send_batch(self._messages(event, event.organization_id, user, identify=False))

    def _resolve_user(self, event: DomainEventEnvelope, organization_id: UUID | None) -> User | None:
        actor_id = _as_uuid(event.actor.id)
        if actor_id is None:
            return None
        if event.actor.type == ActorIdentityType.USER:
            return self.user_repository.get(actor_id)
        if event.event_name == ORGANIZATION_MEMBER_REMOVED and actor_id == _as_uuid(event.payload.get("membership_id")):
            leaver_id = _as_uuid(event.payload.get("user_id"))
            return self.user_repository.get(leaver_id) if leaver_id is not None else None
        if organization_id is None:
            return None
        member = self.organization_user_repository.get_member_with_user_by_membership_id(actor_id, organization_id)
        return member[1] if member is not None else None

    def _messages(
        self, event: DomainEventEnvelope, organization_id: UUID | None, user: User, identify: bool
    ) -> list[dict[str, Any]]:
        installation_id = str(self.installation_repository.get_id())
        common = {"source": SOURCE, "$geoip_disable": True, "$lib": SOURCE}
        groups = {INSTALLATION_GROUP: installation_id}
        name = installation_name(self.config, installation_id)
        properties: dict[str, Any] = {
            **self._event_fields(event),
            **common,
            "installation_id": installation_id,
            "installation_name": name,
        }
        if organization_id is not None:
            groups[ORGANIZATION_GROUP] = str(organization_id)
            properties["organization_id"] = str(organization_id)
        properties["$groups"] = groups
        if self.config.analytics_include_user_details:
            properties["$set"] = {"email": user.email, "name": user.full_name}
        envelope = {"distinct_id": str(user.id), "timestamp": event.occurred_at.isoformat()}
        messages = [{**envelope, "event": event.event_name, "uuid": str(event.event_id), "properties": properties}]
        if not identify:
            return messages
        return [
            *messages,
            {
                **envelope,
                "event": "$groupidentify",
                "uuid": str(uuid5(event.event_id, INSTALLATION_GROUP)),
                "properties": {
                    **common,
                    "$group_type": INSTALLATION_GROUP,
                    "$group_key": installation_id,
                    "$group_set": {"name": name},
                },
            },
        ]

    @staticmethod
    def _event_fields(event: DomainEventEnvelope) -> dict[str, Any]:
        fields = {
            key: str(value) if isinstance(value, UUID) else value
            for key in _EVENT_FIELDS.get(event.event_name, ())
            if (value := event.payload.get(key)) is not None
        }
        if event.event_name == AGENT_UPDATED:
            fields["changed_fields"] = sorted(event.payload.get("field_changes") or {})
        return fields
