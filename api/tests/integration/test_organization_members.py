"""Phase 4a/b (AF-147): org-scoped member management under /organizations/{id}/members.

Owners/admins (and superusers) can list, add, change roles, remove members, resend
invites, and transfer ownership; plain members and cross-org actors are forbidden.
"""

from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_inanyorder,
    contains_string,
    equal_to,
    has_length,
    is_,
    none,
    not_none,
)

from api.domains.rbac.catalog import PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

ORG = uuid7()
OWNER_ID = uuid7()

_GIVEN = [
    prepare_injector(),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _auth(context) -> dict:
    return {
        "Authorization": f"Bearer {context.access_token}",
        "X-Organization-Id": str(ORG),
    }


def _members_url(org_id=ORG) -> str:
    return f"/api/v1/organizations/{org_id}/members"


def _there_is_an_owner():
    """Owner of ORG with an access token; created first so the shared step doesn't
    attach them to an ambient org."""

    def step(context):
        there_is_a_user(
            id=OWNER_ID,
            email="owner@example.com",
            organization_id=ORG,
            role=OrganizationRole.OWNER,
        )(context)
        there_is_an_access_token_for_user(user_id=OWNER_ID)(context)

    return step


def _role_of(context, user_id, org_id=ORG) -> OrganizationRole:
    repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
    return repo.get_by_user_id_and_organization_id(user_id, org_id).role


def test_owner_lists_members():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        with when("the owner lists members"):
            response = context.client.get(_members_url(), headers=_auth(context))

            with then("both members are returned with roles"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(response.json(), has_length(2))
                by_email = {m["email"]: m for m in response.json()}
                assert_that(by_email["owner@example.com"]["role"], equal_to("OWNER"))
                assert_that(by_email["member@example.com"]["role"], equal_to("MEMBER"))


def test_member_search_filters_by_name_and_email():
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                name="Ada Lovelace",
                email="ada@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
            there_is_a_user(
                name="Grace Hopper",
                email="grace@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        by_name = context.client.get(_members_url(), params={"search": "ada"}, headers=_auth(context))
        by_email = context.client.get(_members_url(), params={"search": "GRACE@EXAMPLE"}, headers=_auth(context))
        no_match = context.client.get(_members_url(), params={"search": "nonexistent"}, headers=_auth(context))
        unfiltered = context.client.get(_members_url(), headers=_auth(context))

        assert_that(by_name.status_code, equal_to(status.HTTP_200_OK))
        assert_that([item["full_name"] for item in by_name.json()], equal_to(["Ada Lovelace"]))
        assert_that(by_email.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            [item["full_name"] for item in by_email.json()],
            equal_to(["Grace Hopper"]),
        )
        assert_that(no_match.status_code, equal_to(status.HTTP_200_OK))
        assert_that(no_match.json(), equal_to([]))
        assert_that(
            [item["full_name"] for item in unfiltered.json()],
            contains_inanyorder("Test User", "Ada Lovelace", "Grace Hopper"),
        )


def test_member_list_respects_limit_and_defaults_to_unbounded():
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                name="Ada Lovelace",
                email="ada@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
            there_is_a_user(
                name="Grace Hopper",
                email="grace@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        limited = context.client.get(
            _members_url(), params={"limit": 1}, headers=_auth(context)
        )
        unbounded = context.client.get(_members_url(), headers=_auth(context))

        assert_that(limited.status_code, equal_to(status.HTTP_200_OK))
        assert_that(limited.json(), has_length(1))
        assert_that(unbounded.json(), has_length(3))


def test_superuser_without_membership_read_grant_can_list_members():
    super_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=super_id,
                email="super-members@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
                is_superuser=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(_members_url(), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_owner_cannot_list_members_in_another_active_organization():
    other_org = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                email="other-owner@example.com",
                organization_id=other_org,
                role=OrganizationRole.OWNER,
            ),
        ]
    ) as context:
        response = context.client.get(_members_url(other_org), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_membership_read_cannot_list_members():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.MEMBERSHIP_READ),
        ]
    ) as context:
        response = context.client.get(_members_url(), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_with_assigned_membership_read_cannot_list_members():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            role_lacks_permission(
                OrganizationRole.ADMIN,
                PermissionKey.MEMBERSHIP_READ,
            ),
        ]
    ) as context:
        response = context.client.get(_members_url(), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_plain_member_cannot_manage_members():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        with when("a plain member lists members"):
            response = context.client.get(_members_url(), headers=_auth(context))

            with then("it is forbidden"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_membership_invite_cannot_add_member():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.MEMBERSHIP_INVITE),
        ]
    ) as context:
        response = context.client.post(
            _members_url(),
            json={"email": "blocked@example.com", "role": "MEMBER"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_adds_new_member_and_gets_invite_link():
    with given([*_GIVEN, _there_is_an_owner()]) as context:
        with when("the owner adds a brand-new member by email and name"):
            response = context.client.post(
                _members_url(),
                json={
                    "email": "newbie@example.com",
                    "full_name": "New Bie",
                    "role": "MEMBER",
                },
                headers=_auth(context),
            )

            with then("member created as pending with the given name + invite link"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["member"]["email"], equal_to("newbie@example.com"))
                assert_that(body["member"]["full_name"], equal_to("New Bie"))
                assert_that(body["member"]["role"], equal_to("MEMBER"))
                assert_that(body["member"]["is_pending"], is_(True))
                assert_that(body["invite_link"], contains_string("/set-password?token="))


def test_add_member_with_owner_role_is_rejected():
    with given([*_GIVEN, _there_is_an_owner()]) as context:
        with when("the owner tries to add someone directly as OWNER"):
            response = context.client.post(
                _members_url(),
                json={"email": "x@example.com", "role": "OWNER"},
                headers=_auth(context),
            )

            with then("it is rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_add_existing_active_member_sends_no_invite():
    with given(
        [
            *_GIVEN,
            there_is_a_user(email="existing@example.com"),  # active user, no org
            _there_is_an_owner(),
        ]
    ) as context:
        with when("the owner adds an already-active user"):
            response = context.client.post(
                _members_url(),
                json={"email": "existing@example.com", "role": "ADMIN"},
                headers=_auth(context),
            )

            with then("member added without an invite link"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(response.json()["invite_link"], is_(none()))
                assert_that(response.json()["member"]["role"], equal_to("ADMIN"))


def test_add_duplicate_member_conflicts():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="dupe@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        with when("the owner adds a user already in the org"):
            response = context.client.post(
                _members_url(),
                json={"email": "dupe@example.com", "role": "MEMBER"},
                headers=_auth(context),
            )

            with then("it conflicts"):
                assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_admin_without_membership_role_update_cannot_change_member_role():
    admin_id = uuid7()
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=member_id,
                email="member-role-blocked@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.MEMBERSHIP_ROLE_UPDATE),
        ]
    ) as context:
        response = context.client.patch(
            f"{_members_url()}/{member_id}",
            json={"role": "MEMBER"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_changes_member_role():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        with when("the owner promotes the member to ADMIN"):
            response = context.client.patch(
                f"{_members_url()}/{member_id}",
                json={"role": "ADMIN"},
                headers=_auth(context),
            )

            with then("role is updated"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(response.json()["role"], equal_to("ADMIN"))
                assert_that(_role_of(context, member_id), equal_to(OrganizationRole.ADMIN))


def _there_is_an_admin_actor(admin_id):
    """Org has a separate owner; the access token belongs to an ADMIN of ORG."""

    def step(context):
        _there_is_an_owner()(context)
        there_is_a_user(
            id=admin_id,
            email="admin-actor@example.com",
            organization_id=ORG,
            role=OrganizationRole.ADMIN,
        )(context)
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return step


def test_admin_cannot_promote_member_to_admin():
    admin_id = uuid7()
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        response = context.client.patch(
            f"{_members_url()}/{member_id}",
            json={"role": "ADMIN"},
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_role_of(context, member_id), equal_to(OrganizationRole.MEMBER))


def test_admin_cannot_demote_another_admin():
    admin_id = uuid7()
    other_admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=other_admin_id,
                email="other-admin@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
        ]
    ) as context:
        response = context.client.patch(
            f"{_members_url()}/{other_admin_id}",
            json={"role": "MEMBER"},
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_role_of(context, other_admin_id), equal_to(OrganizationRole.ADMIN))


def test_owner_can_demote_admin_to_member():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=admin_id,
                email="demote-me@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
        ]
    ) as context:
        response = context.client.patch(
            f"{_members_url()}/{admin_id}",
            json={"role": "MEMBER"},
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_role_of(context, admin_id), equal_to(OrganizationRole.MEMBER))


def test_admin_without_membership_remove_cannot_remove_member():
    admin_id = uuid7()
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=member_id,
                email="member-remove-blocked@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.MEMBERSHIP_REMOVE),
        ]
    ) as context:
        response = context.client.delete(f"{_members_url()}/{member_id}", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_removes_member():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
            ),
        ]
    ) as context:
        with when("the owner removes the member"):
            response = context.client.delete(f"{_members_url()}/{member_id}", headers=_auth(context))

            with then("the member is gone"):
                assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
                repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
                assert_that(
                    repo.get_by_user_id_and_organization_id(member_id, ORG),
                    is_(none()),
                )


def test_admin_cannot_remove_another_admin():
    """Removing an admin is as destructive as demoting one, so it's owner-only too."""
    admin_id = uuid7()
    other_admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=other_admin_id,
                email="other-admin-remove@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
        ]
    ) as context:
        response = context.client.delete(f"{_members_url()}/{other_admin_id}", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        assert_that(
            repo.get_by_user_id_and_organization_id(other_admin_id, ORG),
            is_(not_none()),
        )


def test_admin_can_remove_themselves():
    """The other-admin gate must not trap an admin in the org: they can still leave."""
    admin_id = uuid7()
    with given([*_GIVEN, _there_is_an_admin_actor(admin_id)]) as context:
        response = context.client.delete(f"{_members_url()}/{admin_id}", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        assert_that(
            repo.get_by_user_id_and_organization_id(admin_id, ORG),
            is_(none()),
        )


def test_owner_can_remove_admin():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=admin_id,
                email="admin-remove-me@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
        ]
    ) as context:
        response = context.client.delete(f"{_members_url()}/{admin_id}", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        repo: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        assert_that(
            repo.get_by_user_id_and_organization_id(admin_id, ORG),
            is_(none()),
        )


def test_removing_pending_member_revokes_their_invite():
    """A rescinded invite link must stop working once the member is removed."""
    with given([*_GIVEN, _there_is_an_owner()]) as context:
        add = context.client.post(
            _members_url(),
            json={"email": "rescinded@example.com", "role": "MEMBER"},
            headers=_auth(context),
        )
        assert_that(add.status_code, equal_to(status.HTTP_201_CREATED))
        body = add.json()
        member_id = body["member"]["user_id"]
        token = body["invite_link"].split("token=")[1]

        remove = context.client.delete(f"{_members_url()}/{member_id}", headers=_auth(context))
        assert_that(remove.status_code, equal_to(status.HTTP_204_NO_CONTENT))

        # The invite link the (now-removed) user was emailed must be dead.
        accept = context.client.post(
            "/api/v1/auth/set-password",
            json={"token": token, "new_password": "NewPassword123", "full_name": "X"},
        )
        assert_that(accept.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_duplicate_add_does_not_invalidate_existing_invite():
    """Re-adding an already-pending member must 409 without side effects — the invite
    link from the first add must still work (no token rotation, no re-send)."""
    with given([*_GIVEN, _there_is_an_owner()]) as context:
        first = context.client.post(
            _members_url(),
            json={"email": "pending@example.com", "role": "MEMBER"},
            headers=_auth(context),
        )
        assert_that(first.status_code, equal_to(status.HTTP_201_CREATED))
        token = first.json()["invite_link"].split("token=")[1]

        duplicate = context.client.post(
            _members_url(),
            json={"email": "pending@example.com", "role": "ADMIN"},
            headers=_auth(context),
        )
        assert_that(duplicate.status_code, equal_to(status.HTTP_409_CONFLICT))

        # The original invite link must be untouched by the failed duplicate add.
        accept = context.client.post(
            "/api/v1/auth/set-password",
            json={"token": token, "new_password": "NewPassword123", "full_name": "X"},
        )
        assert_that(accept.status_code, equal_to(status.HTTP_200_OK))


def test_cannot_remove_owner():
    with given([*_GIVEN, _there_is_an_owner()]) as context:
        with when("the owner tries to remove themselves (the owner)"):
            response = context.client.delete(f"{_members_url()}/{OWNER_ID}", headers=_auth(context))

            with then("it is rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_owner_transfers_ownership():
    member_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
        ]
    ) as context:
        with when("the owner transfers ownership to the admin"):
            response = context.client.post(
                f"/api/v1/organizations/{ORG}/transfer-ownership",
                json={"user_id": str(member_id)},
                headers=_auth(context),
            )

            with then("ownership swaps atomically"):
                assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
                assert_that(_role_of(context, member_id), equal_to(OrganizationRole.OWNER))
                assert_that(_role_of(context, OWNER_ID), equal_to(OrganizationRole.ADMIN))


def test_admin_cannot_transfer_ownership():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=admin_id,
                email="admin@example.com",
                organization_id=ORG,
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
        ]
    ) as context:
        with when("a non-owner admin tries to transfer ownership"):
            response = context.client.post(
                f"/api/v1/organizations/{ORG}/transfer-ownership",
                json={"user_id": str(admin_id)},
                headers=_auth(context),
            )

            with then("it is forbidden"):
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_membership_invite_cannot_resend_invite():
    admin_id = uuid7()
    pending_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_admin_actor(admin_id),
            there_is_a_user(
                id=pending_id,
                email="pending-blocked@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
                email_verified=False,
            ),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.MEMBERSHIP_INVITE),
        ]
    ) as context:
        response = context.client.post(
            f"{_members_url()}/{pending_id}/resend-invite",
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_resend_invite_for_pending_and_active_member():
    pending_id = uuid7()
    active_id = uuid7()
    with given(
        [
            *_GIVEN,
            _there_is_an_owner(),
            there_is_a_user(
                id=pending_id,
                email="pending@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
                email_verified=False,
            ),
            there_is_a_user(
                id=active_id,
                email="active@example.com",
                organization_id=ORG,
                role=OrganizationRole.MEMBER,
                email_verified=True,
            ),
        ]
    ) as context:
        with when("the owner resends an invite to a pending member"):
            ok = context.client.post(
                f"{_members_url()}/{pending_id}/resend-invite",
                headers=_auth(context),
            )
            with then("a fresh invite link is returned"):
                assert_that(ok.status_code, equal_to(status.HTTP_200_OK))
                assert_that(
                    ok.json()["invite_link"],
                    contains_string("/set-password?token="),
                )

        with when("the owner resends an invite to an already-active member"):
            conflict = context.client.post(
                f"{_members_url()}/{active_id}/resend-invite",
                headers=_auth(context),
            )
            with then("it conflicts"):
                assert_that(conflict.status_code, equal_to(status.HTTP_409_CONFLICT))
