"""Starting, reading, and cancelling Playbook Extractions, and the worker's authority re-check.

A run reads one Agent's transcripts and writes an Organization Skill, so every surface
needs the Agent Permission ``activity.read`` and the Organization Permission
``skill.manage``. The worker acts on the requester's authority, re-checked at start.
"""

from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_length, is_, none, not_none
from sqlmodel import Session, select

from api.domains.events.models import OutboxMessage
from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionStatus
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole, OrganizationUser
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent import (
    there_is_a_skill,
    there_is_agent_access,
    there_is_an_agent,
    there_is_an_agent_in_another_org,
)
from api.tests.steps.agent_memory import signed_in_as
from api.tests.steps.playbooks import (
    playbooks_api_setup,
    process_extraction,
    the_skill_has_a_draft,
    there_is_a_playbook_extraction,
)

_RUNS = "/api/v1/organizations/{organization_id}/agents/{agent_id}/playbook-extractions"
_ORG_RUNS = "/api/v1/organizations/{organization_id}/playbook-extractions"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _runs(context, agent_id=None) -> str:
    return _RUNS.replace("{agent_id}", str(agent_id or context.agent.id))


def _start(context, agent_id=None, **body):
    return context.client.post(
        _runs(context, agent_id), json=body or {"skill_name": "Billing playbook"}, headers=_auth(context)
    )


def _row(context, extraction_id) -> PlaybookExtraction:
    row = context.postgres_delegate.find_by_id(PlaybookExtraction, extraction_id)
    assert row is not None
    return row


def test_an_owner_starts_a_run_that_is_queued_for_the_worker():
    with given(playbooks_api_setup(there_is_an_agent(name="Billing"))) as context:
        with when("an Organization Owner starts a playbook extraction"):
            response = _start(context, skill_name="Billing playbook", window_days=14, max_sessions=10)

        with then("the run is accepted, queued, and handed to the worker"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            body = response.json()
            assert_that(
                body,
                has_entries(
                    status="QUEUED",
                    source_agent_id=str(context.agent.id),
                    source_agent_name="Billing",
                    skill_id=None,
                    skill_name="Billing playbook",
                    max_sessions=10,
                    error_code=None,
                ),
            )
            assert_that(context.queue.enqueued, contains_exactly(_row(context, body["id"]).id))

        with then("the window ends now and starts the requested number of days earlier"):
            row = _row(context, body["id"])
            assert_that(row.window_end - row.window_start, equal_to(timedelta(days=14)))
            assert_that(row.requested_by_membership_id, equal_to(context.organization_user.id))


def test_starting_a_run_records_a_content_free_audit_event_about_the_source_agent():
    with given(playbooks_api_setup(there_is_an_agent(name="Billing"))) as context:
        with when("an Organization Owner starts a playbook extraction"):
            response = _start(context, skill_name="Billing playbook")

        with then("one playbook.extraction.requested event names the run, Agent, and target"):
            with Session(context.postgres_delegate.engine) as session:
                events = session.exec(
                    select(OutboxMessage).where(OutboxMessage.event_name == "playbook.extraction.requested")
                ).all()
            assert_that(events, has_length(1))
            assert_that(
                events[0].payload,
                equal_to(
                    {
                        "organization_id": str(context.organization.id),
                        "extraction_id": response.json()["id"],
                        "agent_id": str(context.agent.id),
                        "skill_id": None,
                        "skill_name": "Billing playbook",
                        "window_days": 30,
                        "max_sessions": 20,
                        "actor_display": context.user.full_name,
                        "subject_display": "Billing",
                    }
                ),
            )


def test_a_run_needs_exactly_one_target():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_skill(name="Existing"))) as context:
        with when("a run names both a new and an existing playbook, and then neither"):
            both = _start(context, skill_name="New", skill_id=str(context.skill.id))
            neither = _start(context, window_days=7)

        with then("both requests are rejected before anything is queued"):
            assert_that(both.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(neither.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(context.queue.enqueued, has_length(0))


def test_a_member_with_agent_owner_access_cannot_extract_without_skill_management():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        )
    ) as context:
        with when("the Member starts, lists, and reads runs for the Agent they own"):
            start = _start(context)
            listing = context.client.get(_runs(context), headers=_auth(context))
            org_listing = context.client.get(_ORG_RUNS, headers=_auth(context))

        with then("each is forbidden because only Owners and Admins manage Organization Skills"):
            assert_that(start.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(listing.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(org_listing.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(context.queue.enqueued, has_length(0))


def test_an_admin_can_extract_from_any_agent_in_the_organization():
    with given(playbooks_api_setup(there_is_an_agent(), signed_in_as(OrganizationRole.ADMIN))) as context:
        with when("an Organization Admin starts a run for an Agent they did not create"):
            response = _start(context)

        with then("their implicit Agent Owner authority and skill.manage allow it"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_an_agent_the_member_cannot_see_is_concealed():
    with given(playbooks_api_setup(there_is_an_agent(), signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member without Agent Access starts a run for it"):
            response = _start(context)

        with then("the Agent is reported as not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_agent_in_another_organization_is_concealed():
    with given(playbooks_api_setup(there_is_an_agent_in_another_org())) as context:
        with when("the Owner starts a run for another Organization's Agent"):
            response = _start(context, context.other_org_agent.id)

        with then("the Agent is reported as not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_only_one_run_per_agent_may_be_active():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_playbook_extraction())) as context:
        with when("a second run is started while the first is queued"):
            response = _start(context, skill_name="Another playbook")

        with then("it conflicts and nothing new is queued"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(context.queue.enqueued, has_length(0))


def test_a_new_playbook_cannot_reuse_an_existing_skill_name():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_skill(name="Billing playbook"))) as context:
        with when("a run asks for a new playbook named like an existing Skill"):
            response = _start(context, skill_name="Billing playbook")

        with then("it conflicts"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_refreshing_a_playbook_records_its_skill_as_the_target():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_skill(name="Billing playbook"))) as context:
        with when("a run refreshes an existing Organization Skill"):
            response = _start(context, skill_id=str(context.skill.id))

        with then("the run targets that lineage under its current name"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(response.json(), has_entries(skill_id=str(context.skill.id), skill_name="Billing playbook"))


def test_a_playbook_with_unpublished_edits_cannot_be_refreshed():
    with given(
        playbooks_api_setup(there_is_an_agent(), there_is_a_skill(name="Billing playbook"), the_skill_has_a_draft())
    ) as context:
        with when("a run targets a Skill whose draft holds a person's edits"):
            response = _start(context, skill_id=str(context.skill.id))

        with then("it conflicts so the draft is never overwritten"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_built_in_skills_cannot_be_playbook_targets():
    with given(
        playbooks_api_setup(there_is_an_agent(), there_is_a_skill(name="aai-crm", global_skill=True))
    ) as context:
        with when("a run targets a built-in Platform Skill"):
            response = _start(context, skill_id=str(context.skill.id))

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_run_that_cannot_be_queued_is_failed_and_reported():
    with given(playbooks_api_setup(there_is_an_agent())) as context:
        context.queue.unavailable = True
        with when("the worker queue is unavailable"):
            response = _start(context)

        with then("the request fails and the stored run is marked as never started"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
            with Session(context.postgres_delegate.engine) as session:
                row = session.exec(select(PlaybookExtraction)).one()
            assert_that(row.status, equal_to(PlaybookExtractionStatus.FAILED))
            assert_that(row.error_code, equal_to("enqueue_failed"))


def test_an_agents_runs_are_listed_newest_first():
    earlier = datetime.now(UTC) - timedelta(days=2)
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_playbook_extraction(
                status=PlaybookExtractionStatus.FAILED, skill_name="First", created_at=earlier
            ),
            there_is_a_playbook_extraction(skill_name="Second"),
        )
    ) as context:
        with when("the Owner lists the Agent's runs"):
            response = context.client.get(_runs(context), headers=_auth(context))

        with then("both are returned, newest first, without playbook content"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(2))
            assert_that([item["skill_name"] for item in body["items"]], contains_exactly("Second", "First"))
            assert_that("result_markdown" in body["items"][0], is_(False))


def test_runs_can_be_listed_by_their_target_skill():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_skill(name="Billing playbook"),
            there_is_a_playbook_extraction(status=PlaybookExtractionStatus.SUCCEEDED, skill_name="Other"),
        )
    ) as context:
        there_is_a_playbook_extraction(
            status=PlaybookExtractionStatus.SUCCEEDED, skill_name="Billing playbook", skill_id=context.skill.id
        )(context)
        with when("the Owner lists the Organization's runs for one Skill"):
            response = context.client.get(_ORG_RUNS, params={"skill_id": str(context.skill.id)}, headers=_auth(context))

        with then("only runs targeting that Skill are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that([item["skill_name"] for item in response.json()["items"]], contains_exactly("Billing playbook"))


def test_runs_of_a_deleted_agent_are_hidden():
    with given(playbooks_api_setup(there_is_an_agent(deleted=True), there_is_a_playbook_extraction())) as context:
        with when("the Owner lists the Organization's runs"):
            response = context.client.get(_ORG_RUNS, headers=_auth(context))

        with then("the deleted Agent's run is not shown"):
            assert_that(response.json()["total"], equal_to(0))


def test_a_run_detail_includes_the_generated_playbook():
    with given(
        playbooks_api_setup(
            there_is_an_agent(), there_is_a_playbook_extraction(status=PlaybookExtractionStatus.SUCCEEDED)
        )
    ) as context:
        context.extraction.result_markdown = "# Billing playbook"
        context.extraction.result_conventions = [{"rule": "Use Vilnius time.", "conversations": 3}]
        context.postgres_delegate.save(context.extraction)
        with when("the Owner opens the run"):
            response = context.client.get(f"{_runs(context)}/{context.extraction.id}", headers=_auth(context))

        with then("the playbook the run produced is included"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["result_markdown"], equal_to("# Billing playbook"))
            assert_that(response.json()["conventions"], equal_to([{"rule": "Use Vilnius time.", "conversations": 3}]))
            assert_that(response.json()["convention_count"], equal_to(1))


def test_a_run_of_another_agent_is_not_found_through_this_agents_path():
    with given(playbooks_api_setup(there_is_an_agent(name="Billing"), there_is_a_playbook_extraction())) as context:
        run_id = context.extraction.id
        there_is_an_agent(name="Triage")(context)
        with when("the run is requested under a different Agent"):
            response = context.client.get(f"{_runs(context)}/{run_id}", headers=_auth(context))

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cancelling_a_queued_run_stops_it_before_the_worker_starts():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_playbook_extraction())) as context:
        with when("the Owner cancels the queued run and the worker then receives it"):
            response = context.client.post(f"{_runs(context)}/{context.extraction.id}/cancel", headers=_auth(context))
            processed = process_extraction(context)

        with then("the run stays cancelled and never starts"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("CANCELLED"))
            assert_that(processed.status, equal_to(PlaybookExtractionStatus.CANCELLED))
            assert_that(processed.started_at, none())


def test_a_finished_run_cannot_be_cancelled():
    with given(
        playbooks_api_setup(
            there_is_an_agent(), there_is_a_playbook_extraction(status=PlaybookExtractionStatus.SUCCEEDED)
        )
    ) as context:
        with when("the Owner cancels a run that already succeeded"):
            response = context.client.post(f"{_runs(context)}/{context.extraction.id}/cancel", headers=_auth(context))

        with then("it conflicts"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_the_worker_fails_a_run_whose_requester_is_no_longer_an_owner_or_admin():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            signed_in_as(OrganizationRole.ADMIN),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        membership = context.postgres_delegate.find_by_id(OrganizationUser, context.organization_user.id)
        membership.role = OrganizationRole.MEMBER
        context.postgres_delegate.save(membership)
        with when("the worker starts a run whose requester was demoted to Member"):
            processed = process_extraction(context)

        with then("the run fails without reading anything"):
            assert_that(processed.status, equal_to(PlaybookExtractionStatus.FAILED))
            assert_that(processed.error_code, equal_to("requester_lost_access"))
            assert_that(processed.session_count, equal_to(0))


def test_the_worker_fails_a_run_whose_requester_left_the_organization():
    with given(
        playbooks_api_setup(there_is_an_agent(), signed_in_as(OrganizationRole.ADMIN), there_is_a_playbook_extraction())
    ) as context:
        context.postgres_delegate.delete_one(OrganizationUser, context.organization_user.id)
        with when("the worker starts the run"):
            processed = process_extraction(context)

        with then("it fails because nobody holds the authority it needs"):
            assert_that(processed.requested_by_membership_id, none())
            assert_that(processed.error_code, equal_to("requester_lost_access"))


def test_the_worker_fails_a_run_whose_source_agent_was_deleted():
    with given(playbooks_api_setup(there_is_an_agent(), there_is_a_playbook_extraction())) as context:
        context.agent.deleted_at = datetime.now(UTC)
        context.postgres_delegate.save(context.agent)
        with when("the worker starts the run"):
            processed = process_extraction(context)

        with then("it fails as the source Agent is unavailable"):
            assert_that(processed.status, equal_to(PlaybookExtractionStatus.FAILED))
            assert_that(processed.error_code, equal_to("source_agent_unavailable"))


def test_the_worker_does_not_take_over_a_run_another_worker_is_processing():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_playbook_extraction(status=PlaybookExtractionStatus.RUNNING, started_at=datetime.now(UTC)),
        )
    ) as context:
        with when("a redelivered message reaches a second worker"):
            processed = process_extraction(context)

        with then("the run is left to the worker processing it"):
            assert_that(processed.status, equal_to(PlaybookExtractionStatus.RUNNING))
            assert_that(processed.finished_at, none())


def test_the_worker_reclaims_a_run_abandoned_by_a_dead_worker():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            there_is_a_playbook_extraction(
                status=PlaybookExtractionStatus.RUNNING, started_at=datetime.now(UTC) - timedelta(hours=1)
            ),
        )
    ) as context:
        with when("a redelivered message arrives an hour after the run started"):
            processed = process_extraction(context)

        with then("the run is processed again and finishes"):
            assert_that(processed.finished_at, not_none())
