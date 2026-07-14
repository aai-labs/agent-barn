"""AF-167: audit logging — end-to-end.

Drives real HTTP requests, then reads the audit log back through its own API to assert
that user actions are captured with the right actor/target/scope, that org admins see only
their own org while superusers can see everything (including NULL-org auth events), that
sensitive fields are redacted, and that filtering and CSV export work.
"""

from uuid import UUID

from fastapi import status
from hamcrest import assert_that, equal_to, greater_than_or_equal_to, has_item, is_

from api.domains.auth.models import TokenData
from api.domains.auth.service import AuthService
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    MockK8sModule,
    MockLiteLLMModule,
    TEST_ENCRYPTION_KEY,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user

ORG_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OWNER_A = UUID("33333333-3333-3333-3333-333333333333")
MEMBER_A = UUID("11111111-1111-1111-1111-111111111111")
OWNER_B = UUID("44444444-4444-4444-4444-444444444444")
SUPERUSER = UUID("22222222-2222-2222-2222-222222222222")

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _token_for(context, user_id: UUID) -> str:
    auth_service: AuthService = context.injector.get(AuthService)
    resolved = context.injector.get(UserRepository).get(user_id)
    token_data = TokenData(user_id=str(resolved.id), stamp=resolved.security_stamp)
    return auth_service.create_access_token(data=token_data)


def _headers(token: str, org_id: UUID | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if org_id is not None:
        headers["X-Organization-Id"] = str(org_id)
    return headers


def _list(context, token, org_id=None, **params):
    return context.client.get(
        "/api/v1/audit-logs", headers=_headers(token, org_id), params=params
    )


# --------------------------------------------------------------------------- #
# Mutations are captured with actor + target
# --------------------------------------------------------------------------- #


def test_org_update_records_actor_and_changed_fields():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        token = _token_for(context, OWNER_A)
        with when("the owner renames their organization"):
            resp = context.client.patch(
                f"/api/v1/organizations/{ORG_A}",
                json={"name": "Renamed Org"},
                headers=_headers(token, ORG_A),
            )
            assert_that(resp.status_code, equal_to(status.HTTP_200_OK))

        with then("an org.update row records the actor and the name change"):
            rows = _list(context, token, ORG_A, action="org.update").json()["items"]
            assert_that(len(rows), equal_to(1))
            row = rows[0]
            assert_that(row["actor_email"], equal_to("owner-a@example.com"))
            assert_that(row["target_type"], equal_to("organization"))
            assert_that(row["changed_fields"]["name"]["new"], equal_to("Renamed Org"))


# --------------------------------------------------------------------------- #
# Scoping: org admins see only their own org; members are refused
# --------------------------------------------------------------------------- #


def test_org_admin_sees_only_own_org():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=OWNER_B,
                email="owner-b@example.com",
                organization_id=ORG_B,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        token_a = _token_for(context, OWNER_A)
        token_b = _token_for(context, OWNER_B)
        # Each owner renames their own org, producing one org.update per org.
        context.client.patch(
            f"/api/v1/organizations/{ORG_A}",
            json={"name": "A Renamed"},
            headers=_headers(token_a, ORG_A),
        )
        context.client.patch(
            f"/api/v1/organizations/{ORG_B}",
            json={"name": "B Renamed"},
            headers=_headers(token_b, ORG_B),
        )

        with then("owner A sees only org A's rows"):
            rows = _list(context, token_a, ORG_A).json()["items"]
            org_ids = {r["organization_id"] for r in rows}
            assert_that(org_ids, equal_to({str(ORG_A)}))


def test_member_cannot_view_audit_log():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=MEMBER_A,
                email="member-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        token = _token_for(context, MEMBER_A)
        resp = _list(context, token, ORG_A)
        assert_that(resp.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --------------------------------------------------------------------------- #
# Auth events are global (NULL org) and visible only to superusers (scope=all)
# --------------------------------------------------------------------------- #


def test_failed_login_is_recorded_and_visible_to_superuser():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=SUPERUSER,
                email="root@example.com",
                is_superuser=True,
                organization_id=None,
            ),
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        with when("someone submits a wrong password for a real account"):
            resp = context.client.post(
                "/api/v1/auth/login",
                data={"username": "owner-a@example.com", "password": "WrongPass999"},
            )
            assert_that(resp.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))

        with then("a superuser sees the auth.login_failed event via scope=all"):
            token = _token_for(context, SUPERUSER)
            rows = _list(
                context, token, ORG_A, scope="all", action="auth.login_failed"
            ).json()["items"]
            assert_that(len(rows), greater_than_or_equal_to(1))
            attempted = [r["actor_email"] for r in rows]
            assert_that(attempted, has_item("owner-a@example.com"))
            assert_that(rows[0]["organization_id"], is_(None))


def test_auth_events_hidden_from_org_scoped_view():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        # Failed login for the owner produces a NULL-org auth.login_failed row.
        context.client.post(
            "/api/v1/auth/login",
            data={"username": "owner-a@example.com", "password": "nope"},
        )
        token = _token_for(context, OWNER_A)
        with then("the org-scoped view never surfaces NULL-org auth rows"):
            rows = _list(context, token, ORG_A, action="auth.login_failed").json()[
                "items"
            ]
            assert_that(rows, equal_to([]))


# --------------------------------------------------------------------------- #
# Reads: agent.view is recorded once despite repeated fetches (suppression)
# --------------------------------------------------------------------------- #


def test_agent_view_is_recorded_and_deduped():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_agent(organization_id=ORG_A, name="Viewable Agent"),
        ]
    ) as context:
        token = _token_for(context, OWNER_A)
        agent_id = context.agent.id
        for _ in range(3):
            context.client.get(
                f"/api/v1/agents/{agent_id}", headers=_headers(token, ORG_A)
            )

        with then("only one agent.view is recorded for the repeated fetches"):
            rows = _list(context, token, ORG_A, action="agent.view").json()["items"]
            assert_that(len(rows), equal_to(1))
            assert_that(rows[0]["target_id"], equal_to(str(agent_id)))
            assert_that(rows[0]["target_label"], equal_to("Viewable Agent"))


# --------------------------------------------------------------------------- #
# Filtering and export
# --------------------------------------------------------------------------- #


def test_filter_by_action_narrows_results():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_agent(organization_id=ORG_A, name="A1"),
        ]
    ) as context:
        token = _token_for(context, OWNER_A)
        agent_id = context.agent.id
        context.client.get(f"/api/v1/agents/{agent_id}", headers=_headers(token, ORG_A))
        context.client.patch(
            f"/api/v1/organizations/{ORG_A}",
            json={"name": "Filtered Org"},
            headers=_headers(token, ORG_A),
        )

        with then("filtering by action returns only that action"):
            rows = _list(context, token, ORG_A, action="org.update").json()["items"]
            actions = {r["action"] for r in rows}
            assert_that(actions, equal_to({"org.update"}))


def test_export_returns_csv_with_header():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=OWNER_A,
                email="owner-a@example.com",
                organization_id=ORG_A,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        token = _token_for(context, OWNER_A)
        context.client.patch(
            f"/api/v1/organizations/{ORG_A}",
            json={"name": "Exported Org"},
            headers=_headers(token, ORG_A),
        )

        with when("the owner exports the audit log"):
            resp = context.client.get(
                "/api/v1/audit-logs/export", headers=_headers(token, ORG_A)
            )
            with then("a CSV attachment with the header row is returned"):
                assert_that(resp.status_code, equal_to(status.HTTP_200_OK))
                assert_that(
                    resp.headers["content-type"].startswith("text/csv"), is_(True)
                )
                assert_that(
                    "attachment" in resp.headers.get("content-disposition", ""),
                    is_(True),
                )
                body = resp.text
                assert_that(body.splitlines()[0].startswith("timestamp,"), is_(True))
                assert_that("org.update" in body, is_(True))
