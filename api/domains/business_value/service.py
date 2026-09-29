from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.business_value.catalogue import DEFAULT_MINUTES, OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import OutcomeMinutesRead, ValueSettingsRead, ValueSettingsUpdate
from api.domains.business_value.repository import ValueSettingsRepository
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy

MINUTES_PER_HOUR = 60
CATALOGUE_OUTCOME_TYPES = frozenset(outcome.value for outcome in OutcomeType)
RATE_QUANTUM = Decimal("0.01")
HOURLY_RATE_FIELD = "hourly_rate_usd"
OUTCOME_MINUTES_FIELD_PREFIX = "outcome_minutes."
READ_DENIED_DETAIL = "You don't have permission to view value for this organization."
MANAGE_DENIED_DETAIL = "You don't have permission to manage value settings for this organization."


@dataclass(frozen=True)
class WriteCategories:
    successful: dict[OutcomeType, int] = field(default_factory=dict)
    unverified: int = 0
    failed: int = 0
    unclassified: int = 0


def effective_minutes(overrides: dict[str, int]) -> dict[OutcomeType, int]:
    return {outcome: overrides.get(outcome.value, default) for outcome, default in DEFAULT_MINUTES.items()}


def value_usd(minutes: int, rate: Decimal | None) -> Decimal | None:
    if rate is None:
        return None
    return Decimal(minutes) * rate / MINUTES_PER_HOUR


def value_to_spend_ratio(value: Decimal | None, spend: Decimal) -> float | None:
    if value is None or spend == 0:
        return None
    return float(value / spend)


def categorise(rows: Sequence[tuple[bool | None, str | None, BusinessActionStatus, int]]) -> WriteCategories:
    successful: dict[OutcomeType, int] = {}
    unverified = failed = unclassified = 0
    for is_write, outcome_type, status, count in rows:
        if is_write is False:
            continue
        if is_write is None or outcome_type not in CATALOGUE_OUTCOME_TYPES:
            unclassified += count
            continue
        if status == BusinessActionStatus.SUCCESS:
            outcome = OutcomeType(outcome_type)
            successful[outcome] = successful.get(outcome, 0) + count
        elif status == BusinessActionStatus.UNKNOWN:
            unverified += count
        else:
            failed += count
    return WriteCategories(successful=successful, unverified=unverified, failed=failed, unclassified=unclassified)


def _rate_text(rate: Decimal | None) -> str | None:
    return None if rate is None else str(rate.quantize(RATE_QUANTUM))


def _minutes_text(minutes: int | None) -> str | None:
    return None if minutes is None else str(minutes)


@inject
@singleton
@dataclass
class BusinessValueService:
    settings_repository: ValueSettingsRepository
    permission_policy: PermissionPolicy
    organization_lookup: OrganizationLookupService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def get_settings(self, organization_id: UUID, context: CurrentUserContext) -> ValueSettingsRead:
        self._require_read(organization_id, context)
        return self._read_settings(organization_id)

    def update_settings(
        self,
        organization_id: UUID,
        data: ValueSettingsUpdate,
        context: CurrentUserContext,
    ) -> ValueSettingsRead:
        self._require_manage(organization_id, context)
        current_rate = self.settings_repository.get_hourly_rate(organization_id)
        overrides = self.settings_repository.get_minute_overrides(organization_id)

        field_changes: dict[str, dict[str, str | None]] = {}
        rate_changed = HOURLY_RATE_FIELD in data.model_fields_set and data.hourly_rate_usd != current_rate
        if rate_changed:
            field_changes[HOURLY_RATE_FIELD] = {
                "previous": _rate_text(current_rate),
                "current": _rate_text(data.hourly_rate_usd),
            }
        minute_changes: dict[str, int | None] = {}
        for outcome, minutes in data.outcome_minutes.items():
            previous = overrides.get(outcome.value)
            if minutes == previous:
                continue
            minute_changes[outcome.value] = minutes
            field_changes[f"{OUTCOME_MINUTES_FIELD_PREFIX}{outcome.value}"] = {
                "previous": _minutes_text(previous),
                "current": _minutes_text(minutes),
            }

        if not field_changes:
            return self._read_settings(organization_id)

        result = self.settings_repository.save_with_event(
            organization_id,
            hourly_rate=data.hourly_rate_usd,
            rate_changed=rate_changed,
            minute_changes=minute_changes,
            field_changes=field_changes,
            actor=resolve_actor_identity(context, organization_id),
            actor_display=context.user.full_name or context.user.email,
            subject_display=self.organization_lookup.get_name(organization_id),
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._read_settings(organization_id)

    def _require_read(self, organization_id: UUID, context: CurrentUserContext) -> AuthorizationScope:
        self.permission_policy.require_organization(
            context, organization_id, PermissionKey.COST_READ, detail=READ_DENIED_DETAIL
        )
        return self.permission_policy.require_organization(
            context, organization_id, PermissionKey.ACTIVITY_READ, detail=READ_DENIED_DETAIL
        )

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require_organization(
            context, organization_id, PermissionKey.ORGANIZATION_UPDATE, detail=MANAGE_DENIED_DETAIL
        )

    def _read_settings(self, organization_id: UUID) -> ValueSettingsRead:
        rate = self.settings_repository.get_hourly_rate(organization_id)
        overrides = self.settings_repository.get_minute_overrides(organization_id)
        effective = effective_minutes(overrides)
        return ValueSettingsRead(
            hourly_rate_usd=float(rate) if rate is not None else None,
            outcome_minutes=[
                OutcomeMinutesRead(
                    outcome_type=outcome,
                    default_minutes=default,
                    override_minutes=overrides.get(outcome.value),
                    effective_minutes=effective[outcome],
                    source="override" if outcome.value in overrides else "default",
                )
                for outcome, default in DEFAULT_MINUTES.items()
            ],
        )
