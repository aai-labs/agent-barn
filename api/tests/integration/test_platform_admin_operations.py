from uuid import UUID, uuid7

import jwt
from fastapi import status
from hamcrest import (
    assert_that,
    contains_inanyorder,
    contains_string,
    equal_to,
    has_entries,
    has_key,
    has_length,
    is_,
    not_,
    not_none,
)
from starlette.testclient import TestClient

from api.core.config import Config
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.events.models import EventScope
from api.domains.events.processor import EventDeliveryProcessor
from api.domains.events.repository import OutboxMessageRepository
from api.domains.events.security_audit import SecurityAuditRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user


def test_platform_admin_can_list_all_users():
    super_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-list-users@example.com",
                is_platform_admin=True,
                email_verified=False,
            ),
            there_is_a_user(email="user-a@example.com"),
            there_is_a_user(email="user-b@example.com"),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/platform/users",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["items"], has_length(3))


def test_platform_admin_creates_pending_user_with_initial_owned_organization():
    actor_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="onboarding-admin@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={
                "email": "new-user@example.com",
                "full_name": "New User",
                "organization_name": "New User Studio",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(body["organization"], not_(has_key("allowed_models")))
        assert_that(
            body,
            has_entries(
                {
                    "invite_link": contains_string("/set-password?token="),
                    "user": has_entries(
                        {
                            "email": "new-user@example.com",
                            "email_verified_at": None,
                        }
                    ),
                    "organization": has_entries({"name": "New User Studio"}),
                }
            ),
        )

        user = context.injector.get(UserRepository).get_by_email("new-user@example.com")
        organization = context.injector.get(OrganizationRepository).get(UUID(body["organization"]["id"]))
        membership = context.injector.get(OrganizationUserRepository).get_by_user_id_and_organization_id(
            user.id, organization.id
        )
        assert_that(organization.created_by_user_id, equal_to(user.id))
        assert_that(membership.role, equal_to(OrganizationRole.OWNER))


def test_platform_user_creation_defaults_org_name_and_rejects_duplicate_email():
    actor_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="create-admin@example.com", is_platform_admin=True),
            there_is_a_user(email="existing@example.com"),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        headers = {"Authorization": f"Bearer {context.access_token}"}
        created = context.client.post(
            "/api/v1/platform/users",
            json={"email": "default-name@example.com", "full_name": "Default Name"},
            headers=headers,
        )
        duplicate = context.client.post(
            "/api/v1/platform/users",
            json={"email": "existing@example.com"},
            headers=headers,
        )

        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(created.json()["organization"]["name"], equal_to("Default Name's Organization"))
        assert_that(duplicate.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_regular_user_cannot_create_platform_user():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="regular-create-user@example.com"),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={"email": "forbidden@example.com"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_resends_invite_only_for_pending_user():
    actor_id = uuid7()
    pending_id = uuid7()
    active_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="resend-admin@example.com", is_platform_admin=True),
            there_is_a_user(id=pending_id, email="pending@example.com", email_verified=False),
            there_is_a_user(id=active_id, email="active@example.com", email_verified=True),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        headers = {"Authorization": f"Bearer {context.access_token}"}
        resent = context.client.post(
            f"/api/v1/platform/users/{pending_id}/resend-invite",
            headers=headers,
        )
        active = context.client.post(
            f"/api/v1/platform/users/{active_id}/resend-invite",
            headers=headers,
        )

        assert_that(resent.status_code, equal_to(status.HTTP_200_OK))
        assert_that(resent.json()["invite_link"], contains_string("/set-password?token="))
        assert_that(active.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_regular_user_cannot_list_users():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="regular-list-users@example.com"),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/platform/users",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_non_user_session_credential_cannot_use_platform_authority():
    actor_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="service-admin@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        config = context.injector.get(Config)
        payload = jwt.decode(
            context.access_token,
            config.secret_signing_key,
            algorithms=[JWT_ENCODING_ALGORITHM],
        )
        payload["credential_class"] = "SERVICE"
        service_token = jwt.encode(
            payload,
            config.secret_signing_key,
            algorithm=JWT_ENCODING_ALGORITHM,
        )

        response = context.client.get(
            "/api/v1/platform/users",
            headers={"Authorization": f"Bearer {service_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_grants_platform_privilege_with_reason_and_domain_event():
    actor_id = uuid7()
    target_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="actor@example.com", is_platform_admin=True),
            there_is_a_user(id=target_id, email="target@example.com"),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/platform/users/{target_id}/platform-privilege",
            json={
                "is_platform_admin": True,
                "reason": "On-call platform operations",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["is_platform_admin"], is_(True))
        target = context.injector.get(UserRepository).get(target_id)
        assert_that(target.is_platform_admin, is_(True))

        outbox_repository = context.injector.get(OutboxMessageRepository)
        assert_that(outbox_repository.count(), equal_to(1))
        message = outbox_repository.get_latest()
        assert_that(message.event_name, equal_to("platform.user_privilege.granted"))
        assert_that(message.event_scope, equal_to(EventScope.PLATFORM))
        assert_that(message.organization_id, is_(None))
        assert_that(message.actor, has_entries({"type": "USER", "id": str(actor_id)}))
        assert_that(message.subject, has_entries({"type": "USER", "id": str(target_id)}))
        assert_that(message.payload["reason"], equal_to("On-call platform operations"))


def test_platform_privilege_event_projects_to_durable_security_audit_record():
    actor_id = uuid7()
    target_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="audit-actor@example.com", is_platform_admin=True),
            there_is_a_user(id=target_id, email="audit-target@example.com"),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/platform/users/{target_id}/platform-privilege",
            json={
                "is_platform_admin": True,
                "reason": "Temporary incident response",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))

        outbox_repository = context.injector.get(OutboxMessageRepository)
        message = outbox_repository.get_latest()
        delivery = outbox_repository.list_deliveries_for_event(message.event_id)[0]
        outbox_repository.mark_delivery_enqueued(delivery.id)
        processed = context.injector.get(EventDeliveryProcessor).process(delivery.id)

        assert_that(processed, is_(True))
        audit_record = context.injector.get(SecurityAuditRepository).get_by_event_id(message.event_id)
        assert_that(audit_record, is_(not_none()))
        assert_that(audit_record.event_scope, equal_to(EventScope.PLATFORM))
        assert_that(audit_record.organization_id, is_(None))
        assert_that(audit_record.action, equal_to("platform.user_privilege.granted"))
        assert_that(audit_record.actor_id, equal_to(str(actor_id)))
        assert_that(audit_record.subject_id, equal_to(str(target_id)))
        assert_that(audit_record.reason, equal_to("Temporary incident response"))


def test_platform_admin_revokes_another_administrator_with_reason():
    actor_id = uuid7()
    target_id = uuid7()

    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="actor-revoke@example.com", is_platform_admin=True),
            there_is_a_user(id=target_id, email="target-revoke@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/platform/users/{target_id}/platform-privilege",
            json={
                "is_platform_admin": False,
                "reason": "Platform rotation completed",
            },
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["is_platform_admin"], is_(False))
        message = context.injector.get(OutboxMessageRepository).get_latest()
        assert_that(message.event_name, equal_to("platform.user_privilege.revoked"))


def test_platform_admin_cannot_revoke_self():
    actor_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="actor-self@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        initial_outbox_count = context.injector.get(OutboxMessageRepository).count()
        response = context.client.patch(
            f"/api/v1/platform/users/{actor_id}/platform-privilege",
            json={"is_platform_admin": False, "reason": "Trying self revoke"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("own"))
        assert_that(
            context.injector.get(OutboxMessageRepository).count(),
            equal_to(initial_outbox_count),
        )


def test_platform_privilege_no_op_is_a_conflict():
    actor_id = uuid7()
    target_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="actor-noop@example.com", is_platform_admin=True),
            there_is_a_user(id=target_id, email="target-noop@example.com"),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        initial_outbox_count = context.injector.get(OutboxMessageRepository).count()
        response = context.client.patch(
            f"/api/v1/platform/users/{target_id}/platform-privilege",
            json={"is_platform_admin": False, "reason": "No actual change"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(
            context.injector.get(OutboxMessageRepository).count(),
            equal_to(initial_outbox_count),
        )


def test_platform_privilege_requires_a_bounded_reason():
    actor_id = uuid7()
    target_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=actor_id, email="actor-reason@example.com", is_platform_admin=True),
            there_is_a_user(id=target_id, email="target-reason@example.com"),
            there_is_an_access_token_for_user(user_id=actor_id),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/platform/users/{target_id}/platform-privilege",
            json={"is_platform_admin": True, "reason": ""},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_platform_admin_can_list_all_organizations():
    super_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-list-orgs@example.com", is_platform_admin=True),
            there_is_a_user(email="owner-org-a@example.com", organization_id=uuid7()),
            there_is_a_user(email="owner-org-b@example.com", organization_id=uuid7()),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            "/api/v1/platform/organizations",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["items"], has_length(2))
        assert_that(body["items"][0], not_(has_key("allowed_models")))


def test_platform_admin_gets_user_detail_with_organization_memberships():
    super_id = uuid7()
    target_id = uuid7()
    org_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-user-detail@example.com", is_platform_admin=True),
            there_is_a_user(
                id=target_id,
                email="detail-target@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/users/{target_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["email"], equal_to("detail-target@example.com"))
        assert_that(body["organization_users"], has_length(1))
        assert_that(body["organization_users"][0]["organization"]["id"], equal_to(str(org_id)))
        assert_that(body["organization_users"][0]["role"], equal_to("MEMBER"))
        assert_that(body["organization_users"][0]["organization"], not_(has_key("allowed_models")))


def test_platform_admin_get_user_detail_404_for_missing_user():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-user-404@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/users/{uuid7()}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_regular_user_cannot_get_platform_user_detail():
    target_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=target_id, email="regular-user-detail@example.com"),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/users/{target_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_gets_organization_detail_with_creator_and_owner_identity():
    super_id = uuid7()
    creator_id = uuid7()
    org_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-org-detail@example.com", is_platform_admin=True),
            there_is_a_user(
                id=creator_id,
                email="org-creator@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["owner_email"], equal_to("org-creator@example.com"))
        assert_that(body, not_(has_key("allowed_models")))
        # there_is_a_user's ad-hoc Organization isn't stamped with created_by_user_id,
        # so Creator is legitimately absent here; a real org (created via the
        # self-service route) always has one. Assert the field is present on the DTO.
        assert_that("creator_email" in body, is_(True))


def test_platform_admin_get_organization_detail_404_for_missing_organization():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-org-404@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{uuid7()}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_regular_user_cannot_get_platform_organization_detail():
    org_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(email="regular-org-detail@example.com", organization_id=org_id),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_lists_organization_members_without_membership():
    super_id = uuid7()
    org_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-members@example.com", is_platform_admin=True),
            there_is_a_user(
                email="owner-member@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="regular-member@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["total"], equal_to(2))
        assert_that(
            [item["email"] for item in body["items"]],
            contains_inanyorder("owner-member@example.com", "regular-member@example.com"),
        )


def test_platform_admin_organization_members_search_and_pagination():
    super_id = uuid7()
    org_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-members-search@example.com", is_platform_admin=True),
            there_is_a_user(
                email="findme-owner@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="other-member@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        headers = {"Authorization": f"Bearer {context.access_token}"}
        search_response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}/members",
            params={"search": "findme"},
            headers=headers,
        )
        paginated_response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}/members",
            params={"page": 1, "page_size": 1},
            headers=headers,
        )

        assert_that(search_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(search_response.json()["items"], has_length(1))
        assert_that(search_response.json()["items"][0]["email"], equal_to("findme-owner@example.com"))

        assert_that(paginated_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(paginated_response.json()["items"], has_length(1))
        assert_that(paginated_response.json()["total"], equal_to(2))


def test_platform_admin_organization_members_404_for_missing_organization():
    super_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(id=super_id, email="super-members-404@example.com", is_platform_admin=True),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{uuid7()}/members",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_regular_user_cannot_list_platform_organization_members():
    org_id = uuid7()
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="regular-members-list@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/platform/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
