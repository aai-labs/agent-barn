"""Integration tests for the Tier catalog (Tiers, PR 1).

Platform Administrators keep the catalog. The migration seeds the pricing page's Tiers and
the system's none Tier, all switched off. Each Tier stays coherent with how it is activated,
its key and activation never change, the system's Free and none Tiers are never deleted, and
none never changes. Every change is audited. No Organization is on a Tier yet.
"""

from uuid import uuid4, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_inanyorder, equal_to, has_entries, has_length

from api.domains.events.catalog import PLATFORM_TIER_CHANGED, PLATFORM_TIER_CREATED, PLATFORM_TIER_DELETED
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.tiers.models import SEED_TIERS
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_URL = "/api/v1/platform/tiers"
_IDS = {str(seed["key"]): str(seed["id"]) for seed in SEED_TIERS}

_BASE_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]

_TIER_3 = {
    "key": "cloud_3",
    "name": "Cloud Tier 3",
    "activation": "paid",
    "price_usd": "250",
    "price_note": "per month",
    "monthly_usage_usd": "250",
    "one_time_credit_usd": "10",
    "agent_limit": 10,
    "features": ["team", "custom_agents"],
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(email: str):
    """A Platform Administrator with no Membership, whose token lands last in context."""
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


def _admin_given(email: str) -> list:
    return [*_BASE_GIVEN, *_platform_admin(email)]


def _create(context, body: dict | None = None):
    return context.client.post(_URL, json=body or _TIER_3, headers=_auth(context.access_token))


def _patch(context, key: str, body: dict):
    return context.client.patch(f"{_URL}/{_IDS[key]}", json=body, headers=_auth(context.access_token))


def _tiers(context) -> list[dict]:
    return context.client.get(_URL, headers=_auth(context.access_token)).json()


def _tier(context, key: str) -> dict:
    return next(tier for tier in _tiers(context) if tier["key"] == key)


def _events(context, name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == name]


# --- authorization -------------------------------------------------------


def test_the_catalog_requires_authentication():
    with given(_BASE_GIVEN) as context:
        assert_that(context.client.get(_URL).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_an_organization_owner_can_neither_read_nor_change_the_catalog():
    with given([*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="tier-owner@example.com")]) as (
        context
    ):
        headers = _auth(context.access_token)

        assert_that(context.client.get(_URL, headers=headers).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(
            context.client.post(_URL, json=_TIER_3, headers=headers).status_code, equal_to(status.HTTP_403_FORBIDDEN)
        )
        assert_that(
            context.client.patch(f"{_URL}/{_IDS['cloud_1']}", json={"enabled": True}, headers=headers).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )
        assert_that(
            context.client.delete(f"{_URL}/{_IDS['pilot']}", headers=headers).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_a_read_only_api_key_can_read_the_catalog_but_not_change_it():
    with given(_admin_given("tier-admin-key@example.com")) as context:
        response = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(context.access_token),
        )
        key = _auth(response.json()["token"])

        assert_that(context.client.get(_URL, headers=key).status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            context.client.post(_URL, json=_TIER_3, headers=key).status_code, equal_to(status.HTTP_403_FORBIDDEN)
        )
        assert_that(_tiers(context), has_length(len(SEED_TIERS)))


# --- the seeded catalog --------------------------------------------------


def test_the_catalog_starts_with_the_pricing_page_tiers_switched_off():
    with given(_admin_given("tier-admin-list@example.com")) as context:
        tiers = _tiers(context)

        assert_that([tier["key"] for tier in tiers], contains_exactly("free", "cloud_1", "cloud_2", "pilot", "none"))
        assert_that([tier["enabled"] for tier in tiers], equal_to([False] * 5))
        free, cloud_1, cloud_2, pilot, none = tiers
        assert_that(
            free,
            has_entries(
                activation="free",
                price_usd="0.00",
                one_time_credit_usd="10.00",
                agent_limit=1,
                allowed_platform_keys=["agentbarn_telegram", "web"],
                features=["team"],
                is_system=True,
            ),
        )
        assert_that(
            cloud_1,
            has_entries(
                activation="paid",
                price_usd="20.00",
                monthly_usage_usd="20.00",
                one_time_credit_usd="10.00",
                agent_limit=1,
                allowed_platform_keys=None,
                is_system=False,
            ),
        )
        assert_that("priority_support" in cloud_1["features"], equal_to(False))
        assert_that(cloud_2, has_entries(price_usd="100.00", monthly_usage_usd="100.00", agent_limit=4))
        assert_that("priority_support" in cloud_2["features"], equal_to(True))
        assert_that(
            pilot,
            has_entries(activation="contact", price_usd="500.00", contact_url="https://agentbarn.dev/pricing"),
        )
        assert_that(
            none,
            has_entries(activation="none", agent_limit=0, allowed_platform_keys=[], features=[], is_system=True),
        )


# --- adding a Tier -------------------------------------------------------


def test_a_created_tier_is_listed_and_audited_with_its_values():
    with given(_admin_given("tier-admin-create@example.com")) as context:
        response = _create(context)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
        created = response.json()
        assert_that(
            created,
            has_entries(
                key="cloud_3",
                enabled=False,
                monthly_usage_usd="250.00",
                # Stored in declaration order, so equal sets compare equal.
                features=["custom_agents", "team"],
                is_system=False,
            ),
        )
        assert_that([tier["key"] for tier in _tiers(context)], has_length(len(SEED_TIERS) + 1))
        (event,) = _events(context, PLATFORM_TIER_CREATED)
        assert_that(event.event_scope, equal_to(EventScope.PLATFORM))
        assert_that(
            event.payload,
            has_entries(
                subject_display="Cloud Tier 3",
                key="cloud_3",
                activation="paid",
                price_usd=250.0,
                monthly_usage_usd=250.0,
                agent_limit=10,
            ),
        )


@pytest.mark.parametrize(
    "override",
    [
        {"activation": "free"},
        {"activation": "none"},
        {"price_usd": "0"},
        {"activation": "contact", "contact_url": "https://example.com/talk"},
        {"activation": "contact", "monthly_usage_usd": "0"},
        {"activation": "contact", "monthly_usage_usd": "0", "contact_url": "http://example.com/talk"},
        {"agent_limit": 0},
        {"allowed_platform_keys": ["myspace"]},
        {"features": ["unlimited_everything"]},
        {"key": "Cloud 3"},
        {"price_usd": "-5"},
        {"price_usd": "20.005"},
    ],
)
def test_a_tier_that_does_not_hold_together_is_refused(override):
    with given(_admin_given(f"tier-admin-refuse-{uuid4().hex[:8]}@example.com")) as context:
        response = _create(context, {**_TIER_3, **override})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT), response.text)
        assert_that(_events(context, PLATFORM_TIER_CREATED), equal_to([]))


def test_a_contact_only_tier_needs_a_secure_link_and_grants_no_monthly_usage():
    with given(_admin_given("tier-admin-contact@example.com")) as context:
        response = _create(
            context,
            {
                "key": "enterprise",
                "name": "Enterprise",
                "activation": "contact",
                "price_usd": "0",
                "agent_limit": 50,
                "contact_url": "https://agentbarn.dev/contact",
            },
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
        assert_that(response.json(), has_entries(activation="contact", monthly_usage_usd="0.00"))


def test_keys_and_names_are_unique():
    with given(_admin_given("tier-admin-unique@example.com")) as context:
        same_key = _create(context, {**_TIER_3, "key": "cloud_1"})
        same_name = _create(context, {**_TIER_3, "name": "  cloud tier 1 "})

        assert_that(same_key.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(same_name.status_code, equal_to(status.HTTP_409_CONFLICT))


# --- changing a Tier -----------------------------------------------------


def test_each_changed_setting_leaves_one_event_and_an_unchanged_save_none():
    with given(_admin_given("tier-admin-patch@example.com")) as context:
        response = _patch(context, "cloud_2", {"enabled": True, "agent_limit": 5, "price_note": "per month"})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json(), has_entries(enabled=True, agent_limit=5))
        events = _events(context, PLATFORM_TIER_CHANGED)
        assert_that(
            [event.payload for event in events],
            contains_inanyorder(
                has_entries(setting="enabled", previous=False, current=True, subject_display="Cloud Tier 2"),
                has_entries(setting="agent_limit", previous=4, current=5),
            ),
        )

        with when("the same values are saved again"):
            _patch(context, "cloud_2", {"enabled": True, "agent_limit": 5})

        with then("nothing more is recorded"):
            assert_that(_events(context, PLATFORM_TIER_CHANGED), has_length(2))


def test_amounts_are_audited_as_numbers_and_platforms_can_be_opened_to_all():
    with given(_admin_given("tier-admin-amounts@example.com")) as context:
        _patch(context, "free", {"one_time_credit_usd": "5.50", "allowed_platform_keys": None})

        assert_that(_tier(context, "free"), has_entries(one_time_credit_usd="5.50", allowed_platform_keys=None))
        assert_that(
            [event.payload for event in _events(context, PLATFORM_TIER_CHANGED)],
            contains_inanyorder(
                has_entries(setting="one_time_credit_usd", previous=10.0, current=5.5),
                has_entries(setting="allowed_platform_keys", previous=["agentbarn_telegram", "web"], current=None),
            ),
        )


@pytest.mark.parametrize(
    ("key", "body"),
    [
        ("free", {"price_usd": "5"}),
        ("free", {"monthly_usage_usd": "5"}),
        ("cloud_1", {"price_usd": "0"}),
        ("pilot", {"contact_url": None}),
        ("pilot", {"monthly_usage_usd": "10"}),
        ("cloud_1", {"agent_limit": None}),
        ("cloud_1", {"key": "starter"}),
        ("cloud_1", {"activation": "contact"}),
    ],
)
def test_an_edit_is_checked_against_the_values_it_keeps(key, body):
    with given(_admin_given(f"tier-admin-keep-{uuid4().hex[:8]}@example.com")) as context:
        response = _patch(context, key, body)

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT), response.text)
        assert_that(_events(context, PLATFORM_TIER_CHANGED), equal_to([]))


def test_a_name_another_tier_has_is_refused_on_edit():
    with given(_admin_given("tier-admin-rename@example.com")) as context:
        response = _patch(context, "cloud_2", {"name": "CLOUD TIER 1"})

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_the_none_tier_never_changes():
    with given(_admin_given("tier-admin-none@example.com")) as context:
        response = _patch(context, "none", {"name": "Locked out"})

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_tier(context, "none"), has_entries(name="No tier"))


def test_an_unknown_tier_is_not_found():
    with given(_admin_given("tier-admin-unknown@example.com")) as context:
        headers = _auth(context.access_token)

        assert_that(
            context.client.patch(f"{_URL}/{uuid7()}", json={"enabled": True}, headers=headers).status_code,
            equal_to(status.HTTP_404_NOT_FOUND),
        )
        assert_that(
            context.client.delete(f"{_URL}/{uuid7()}", headers=headers).status_code,
            equal_to(status.HTTP_404_NOT_FOUND),
        )


# --- deleting a Tier -----------------------------------------------------


@pytest.mark.parametrize("key", ["free", "none"])
def test_the_system_tiers_are_never_deleted(key):
    with given(_admin_given(f"tier-admin-system-{key}@example.com")) as context:
        response = context.client.delete(f"{_URL}/{_IDS[key]}", headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_tiers(context), has_length(len(SEED_TIERS)))


def test_any_other_tier_can_be_deleted_and_the_deletion_is_audited():
    with given(_admin_given("tier-admin-delete@example.com")) as context:
        response = context.client.delete(f"{_URL}/{_IDS['pilot']}", headers=_auth(context.access_token))

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that("pilot" in [tier["key"] for tier in _tiers(context)], equal_to(False))
        (event,) = _events(context, PLATFORM_TIER_DELETED)
        assert_that(event.payload, has_entries(key="pilot", activation="contact", price_usd=500.0))
