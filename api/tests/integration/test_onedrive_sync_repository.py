from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, is_not, none, not_none
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.domains.onedrive_sync.lookup import OneDriveSyncLookupService
from api.domains.onedrive_sync.models import OneDriveSyncConnection, OneDriveSyncStatus
from api.domains.onedrive_sync.repository import OneDriveSyncConnectionConflict, OneDriveSyncRepository
from api.domains.organizations.repository import OrganizationRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization

_TENANT_ID = "22222222-2222-4222-8222-222222222222"
_SITE_ID = "contoso.sharepoint.com,aaa,bbb"
_SITE_URL = "https://contoso.sharepoint.com/sites/AgentBarnTest"
_FOLDER_URL = "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn"

_GIVEN = [prepare_injector(), database_repo_is_ready(), there_is_an_organization()]


def _repository(context) -> OneDriveSyncRepository:
    return context.injector.get(OneDriveSyncRepository)


def _create_pending(context, token: str = "encrypted-token") -> OneDriveSyncConnection:
    return _repository(context).create_pending(
        context.organization.id,
        tenant_id=_TENANT_ID,
        connected_by_user_id=context.user.id,
        pending_access_token=token,
        pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _activate(context, connection: OneDriveSyncConnection) -> OneDriveSyncConnection | None:
    return _repository(context).activate(
        connection.id,
        site_id=_SITE_ID,
        site_name="Agent Barn Test",
        site_url=_SITE_URL,
        folder_item_id="item-1",
        folder_web_url=_FOLDER_URL,
        permission_id="perm-1",
    )


def test_a_pending_connection_is_the_organizations_open_connection():
    with given(_GIVEN) as context:
        created = _create_pending(context)

        found = _repository(context).get_open(context.organization.id)

        assert_that(found, not_none())
        assert found is not None
        assert_that(found.id, equal_to(created.id))
        assert_that(found.status, equal_to(OneDriveSyncStatus.PENDING))
        assert_that(found.tenant_id, equal_to(_TENANT_ID))
        assert_that(found.connected_by_user_id, equal_to(context.user.id))
        assert_that(found.pending_access_token, equal_to("encrypted-token"))


def test_another_organization_has_no_open_connection():
    with given(_GIVEN) as context:
        _create_pending(context)

        assert_that(_repository(context).get_open(uuid7()), none())


def test_a_new_sign_in_replaces_the_pending_connection():
    with given(_GIVEN) as context:
        first = _create_pending(context, token="first")

        second = _create_pending(context, token="second")

        found = _repository(context).get_open(context.organization.id)
        assert found is not None
        assert_that(second.id, is_not(equal_to(first.id)))
        assert_that(found.id, equal_to(second.id))
        assert_that(found.pending_access_token, equal_to("second"))


def test_a_sign_in_is_refused_while_a_connection_is_active():
    with given(_GIVEN) as context:
        _activate(context, _create_pending(context))

        with pytest.raises(OneDriveSyncConnectionConflict):
            _create_pending(context)


def test_activating_records_the_site_and_folder_and_forgets_the_token():
    with given(_GIVEN) as context:
        pending = _create_pending(context)

        active = _activate(context, pending)

        assert active is not None
        assert_that(active.status, equal_to(OneDriveSyncStatus.ACTIVE))
        assert_that(active.site_id, equal_to(_SITE_ID))
        assert_that(active.site_name, equal_to("Agent Barn Test"))
        assert_that(active.site_url, equal_to(_SITE_URL))
        assert_that(active.folder_item_id, equal_to("item-1"))
        assert_that(active.folder_web_url, equal_to(_FOLDER_URL))
        assert_that(active.permission_id, equal_to("perm-1"))
        assert_that(active.connected_at, not_none())
        assert_that(active.pending_access_token, none())
        assert_that(active.pending_expires_at, none())


def test_only_a_pending_connection_can_be_activated():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None

        assert_that(_activate(context, active), none())


def test_a_disconnected_connection_is_no_longer_open():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None

        disconnected = _repository(context).mark_disconnected(active.id)

        assert disconnected is not None
        assert_that(disconnected.status, equal_to(OneDriveSyncStatus.DISCONNECTED))
        assert_that(disconnected.disconnected_at, not_none())
        assert_that(_repository(context).get_open(context.organization.id), none())


def test_only_an_active_connection_can_be_disconnected():
    with given(_GIVEN) as context:
        pending = _create_pending(context)

        assert_that(_repository(context).mark_disconnected(pending.id), none())


def test_an_organization_can_connect_again_after_disconnecting():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None
        _repository(context).mark_disconnected(active.id)

        again = _create_pending(context)

        found = _repository(context).get_open(context.organization.id)
        assert found is not None
        assert_that(found.id, equal_to(again.id))


def test_abandoning_removes_only_a_pending_connection():
    with given(_GIVEN) as context:
        _create_pending(context)

        assert_that(_repository(context).delete_pending(context.organization.id), equal_to(True))
        assert_that(_repository(context).get_open(context.organization.id), none())


def test_abandoning_leaves_an_active_connection_in_place():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None

        assert_that(_repository(context).delete_pending(context.organization.id), equal_to(False))
        found = _repository(context).get_open(context.organization.id)
        assert found is not None
        assert_that(found.id, equal_to(active.id))


def test_the_database_allows_one_open_connection_per_organization():
    with given(_GIVEN) as context:
        with Session(context.postgres_delegate.engine) as session:
            for _ in range(2):
                session.add(
                    OneDriveSyncConnection(
                        organization_id=context.organization.id,
                        status=OneDriveSyncStatus.PENDING,
                        tenant_id=_TENANT_ID,
                    )
                )
            with pytest.raises(IntegrityError):
                session.commit()


def test_deleting_the_organization_deletes_its_connection():
    with given(_GIVEN) as context:
        created = _create_pending(context)

        context.injector.get(OrganizationRepository).delete(context.organization.id)

        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get(OneDriveSyncConnection, created.id), none())


def test_the_lookup_names_the_active_folder_site():
    with given(_GIVEN) as context:
        lookup = context.injector.get(OneDriveSyncLookupService)
        pending = _create_pending(context)
        assert_that(lookup.folder_site_id(context.organization.id), none())

        _activate(context, pending)

        assert_that(lookup.folder_site_id(context.organization.id), equal_to(_SITE_ID))
        assert_that(lookup.folder_site_id(uuid7()), none())
