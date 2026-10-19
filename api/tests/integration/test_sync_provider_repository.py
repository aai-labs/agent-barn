from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, is_not, none, not_none
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.domains.organizations.repository import OrganizationRepository
from api.domains.sync_provider.lookup import SyncProviderLookupService
from api.domains.sync_provider.models import SyncProviderConnection, SyncProviderStatus
from api.domains.sync_provider.repository import SyncProviderConnectionConflict, SyncProviderRepository
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.sync_provider import OTHER_DRIVE, OtherDriveModule

_ONEDRIVE = "onedrive"
_DROPBOX = "dropbox"
_ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"
_SITE_ID = "contoso.sharepoint.com,aaa,bbb"
_SITE_URL = "https://contoso.sharepoint.com/sites/AgentBarnTest"
_FOLDER_URL = "https://contoso.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn"

_GIVEN = [prepare_injector(), database_repo_is_ready(), there_is_an_organization()]


def _repository(context) -> SyncProviderRepository:
    return context.injector.get(SyncProviderRepository)


def _create_pending(context, provider_key: str = _ONEDRIVE, token: str = "encrypted-token") -> SyncProviderConnection:
    return _repository(context).create_pending(
        context.organization.id,
        provider_key,
        schema_version=1,
        account_id=_ACCOUNT_ID,
        connected_by_user_id=context.user.id,
        credentials_encrypted=token,
        pending_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _activate(context, connection: SyncProviderConnection) -> SyncProviderConnection | None:
    return _repository(context).activate(
        connection.id,
        location_id=_SITE_ID,
        location_name="Agent Barn Test",
        location_url=_SITE_URL,
        folder_id="item-1",
        folder_web_url=_FOLDER_URL,
        provider_data={"permission_id": "perm-1"},
    )


def test_a_pending_connection_is_the_providers_open_connection():
    with given(_GIVEN) as context:
        created = _create_pending(context)

        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)

        assert found is not None
        assert_that(found.id, equal_to(created.id))
        assert_that(found.provider_key, equal_to(_ONEDRIVE))
        assert_that(found.schema_version, equal_to(1))
        assert_that(found.status, equal_to(SyncProviderStatus.PENDING))
        assert_that(found.account_id, equal_to(_ACCOUNT_ID))
        assert_that(found.connected_by_user_id, equal_to(context.user.id))
        assert_that(found.credentials_encrypted, equal_to("encrypted-token"))
        assert_that(found.provider_data, equal_to({}))


def test_another_provider_or_organization_has_no_open_connection():
    with given(_GIVEN) as context:
        _create_pending(context)

        assert_that(_repository(context).get_open(context.organization.id, _DROPBOX), none())
        assert_that(_repository(context).get_open(uuid7(), _ONEDRIVE), none())


def test_the_organizations_open_connections_are_listed_across_providers():
    with given(_GIVEN) as context:
        created = _create_pending(context)

        listed = _repository(context).list_open(context.organization.id)

        assert_that([connection.id for connection in listed], equal_to([created.id]))
        assert_that(_repository(context).list_open(uuid7()), equal_to([]))


def test_a_new_sign_in_replaces_the_pending_connection():
    with given(_GIVEN) as context:
        first = _create_pending(context, token="first")

        second = _create_pending(context, token="second")

        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)
        assert found is not None
        assert_that(second.id, is_not(equal_to(first.id)))
        assert_that(found.id, equal_to(second.id))
        assert_that(found.credentials_encrypted, equal_to("second"))


def test_a_sign_in_is_refused_while_a_connection_is_active():
    with given(_GIVEN) as context:
        _activate(context, _create_pending(context))

        with pytest.raises(SyncProviderConnectionConflict):
            _create_pending(context)


def test_activating_records_the_location_and_folder_and_forgets_the_token():
    with given(_GIVEN) as context:
        pending = _create_pending(context)

        active = _activate(context, pending)

        assert active is not None
        assert_that(active.status, equal_to(SyncProviderStatus.ACTIVE))
        assert_that(active.location_id, equal_to(_SITE_ID))
        assert_that(active.location_name, equal_to("Agent Barn Test"))
        assert_that(active.location_url, equal_to(_SITE_URL))
        assert_that(active.folder_id, equal_to("item-1"))
        assert_that(active.folder_web_url, equal_to(_FOLDER_URL))
        assert_that(active.connected_at, not_none())
        assert_that(active.credentials_encrypted, none())
        assert_that(active.pending_expires_at, none())


def test_provider_data_is_stored_and_read_back():
    with given(_GIVEN) as context:
        _activate(context, _create_pending(context))

        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)

        assert found is not None
        assert_that(found.provider_data, equal_to({"permission_id": "perm-1"}))


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
        assert_that(disconnected.status, equal_to(SyncProviderStatus.DISCONNECTED))
        assert_that(disconnected.disconnected_at, not_none())
        assert_that(_repository(context).get_open(context.organization.id, _ONEDRIVE), none())
        assert_that(_repository(context).list_open(context.organization.id), equal_to([]))


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

        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)
        assert found is not None
        assert_that(found.id, equal_to(again.id))


def test_abandoning_removes_only_that_providers_pending_connection():
    with given(_GIVEN) as context:
        _create_pending(context)

        assert_that(_repository(context).delete_pending(context.organization.id, _DROPBOX), equal_to(False))
        assert_that(_repository(context).get_open(context.organization.id, _ONEDRIVE), not_none())
        assert_that(_repository(context).delete_pending(context.organization.id, _ONEDRIVE), equal_to(True))
        assert_that(_repository(context).get_open(context.organization.id, _ONEDRIVE), none())


def test_clearing_expired_sign_ins_removes_only_expired_pending_connections():
    with given(_GIVEN) as context:
        expired = _repository(context).create_pending(
            context.organization.id,
            _ONEDRIVE,
            schema_version=1,
            account_id=_ACCOUNT_ID,
            connected_by_user_id=context.user.id,
            credentials_encrypted="token",
            pending_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        _repository(context).delete_expired_pending(context.organization.id)

        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get(SyncProviderConnection, expired.id), none())
        fresh = _create_pending(context)
        _repository(context).delete_expired_pending(context.organization.id)
        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)
        assert found is not None
        assert_that(found.id, equal_to(fresh.id))


def test_clearing_expired_sign_ins_leaves_an_active_connection():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None

        _repository(context).delete_expired_pending(context.organization.id)

        assert_that(_repository(context).get_open(context.organization.id, _ONEDRIVE), not_none())


def test_abandoning_leaves_an_active_connection_in_place():
    with given(_GIVEN) as context:
        active = _activate(context, _create_pending(context))
        assert active is not None

        assert_that(_repository(context).delete_pending(context.organization.id, _ONEDRIVE), equal_to(False))
        found = _repository(context).get_open(context.organization.id, _ONEDRIVE)
        assert found is not None
        assert_that(found.id, equal_to(active.id))


def test_the_database_refuses_a_non_positive_schema_version():
    with given(_GIVEN) as context:
        with Session(context.postgres_delegate.engine) as session:
            session.add(
                SyncProviderConnection(
                    organization_id=context.organization.id,
                    provider_key=_ONEDRIVE,
                    schema_version=0,
                    status=SyncProviderStatus.PENDING,
                    account_id=_ACCOUNT_ID,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()


# --- one connection at a time ---
#
# The partial unique index on organization_id is the database half of "one provider at a
# time". Allowing several providers means indexing (organization_id, provider_key) instead,
# and these two tests change with it.


def test_the_database_allows_one_open_connection_per_organization_across_providers():
    with given(_GIVEN) as context:
        with Session(context.postgres_delegate.engine) as session:
            for provider_key in (_ONEDRIVE, _DROPBOX):
                session.add(
                    SyncProviderConnection(
                        organization_id=context.organization.id,
                        provider_key=provider_key,
                        status=SyncProviderStatus.PENDING,
                        account_id=_ACCOUNT_ID,
                    )
                )
            with pytest.raises(IntegrityError):
                session.commit()


def test_a_second_providers_sign_in_is_refused_while_another_is_open():
    with given(_GIVEN) as context:
        _create_pending(context, _ONEDRIVE)

        with pytest.raises(SyncProviderConnectionConflict):
            _create_pending(context, _DROPBOX)

        assert_that(_repository(context).get_open(context.organization.id, _ONEDRIVE), not_none())


# --- lifecycle around the Organization ---


def test_deleting_the_organization_deletes_its_connection():
    with given(_GIVEN) as context:
        created = _create_pending(context)

        context.injector.get(OrganizationRepository).delete(context.organization.id)

        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get(SyncProviderConnection, created.id), none())


def test_the_lookup_names_the_sharepoint_folder_site_of_an_active_connection():
    with given(_GIVEN) as context:
        lookup = context.injector.get(SyncProviderLookupService)
        pending = _create_pending(context)
        assert_that(lookup.sharepoint_folder_site_id(context.organization.id), none())

        _activate(context, pending)

        assert_that(lookup.sharepoint_folder_site_id(context.organization.id), equal_to(_SITE_ID))
        assert_that(lookup.sharepoint_folder_site_id(uuid7()), none())


def test_the_lookup_ignores_a_provider_without_the_sharepoint_guard():
    with given(
        [prepare_injector(modules=[OtherDriveModule()]), database_repo_is_ready(), there_is_an_organization()]
    ) as context:
        lookup = context.injector.get(SyncProviderLookupService)

        _activate(context, _create_pending(context, OTHER_DRIVE))

        assert_that(lookup.sharepoint_folder_site_id(context.organization.id), none())


def test_the_lookup_ignores_a_provider_that_is_no_longer_shipped():
    with given(_GIVEN) as context:
        _activate(context, _create_pending(context, _DROPBOX))

        assert_that(
            context.injector.get(SyncProviderLookupService).sharepoint_folder_site_id(context.organization.id), none()
        )
