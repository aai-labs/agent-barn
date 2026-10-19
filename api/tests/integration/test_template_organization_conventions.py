"""Adding reviewed Organization Conventions to a Template draft's AGENTS.md.

The rules land in a marked section of the draft; publishing stays with the person,
and the draft's other content and required Skills are left as they were.
"""

from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_entries, is_not
from sqlmodel import Session, select

from api.domains.agents.models import AgentTemplateDraftSkill
from api.domains.templates.conventions import START_MARKER
from api.domains.templates.models import AgentTemplate, AgentTemplateDraft
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent import there_is_a_skill
from api.tests.steps.agent_memory import signed_in_as
from api.tests.steps.playbooks import playbooks_api_setup
from api.tests.steps.template import (
    there_is_a_template,
    there_is_an_org_template_draft,
    there_is_an_org_template_draft_skill,
)

_CONVENTIONS = "/api/v1/organizations/{organization_id}/templates/{template_key}/draft/conventions"
RULES = ["Use Vilnius time for dates and deadlines.", "Ask for approval before changing records."]


def _add(context, rules=RULES, template_key="sales"):
    return context.client.post(
        _CONVENTIONS.replace("{template_key}", template_key),
        json={"rules": rules},
        headers={"Authorization": f"Bearer {context.access_token}"},
    )


def _draft(context, template_key="sales") -> AgentTemplateDraft:
    with Session(context.postgres_delegate.engine) as session:
        return session.exec(select(AgentTemplateDraft).where(AgentTemplateDraft.template_key == template_key)).one()


def test_rules_start_a_draft_with_a_conventions_section_and_leave_the_published_version_alone():
    with given(
        playbooks_api_setup(there_is_a_template(template_key="sales", agents_md="# Agents\n\nSell well.\n"))
    ) as context:
        with when("an Owner adds two reviewed rules to a Template without a draft"):
            response = _add(context)

        with then("both are added to a new draft's AGENTS.md after its existing instructions"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to({"template_key": "sales", "added": 2, "already_present": 0}))
            agents_md = _draft(context).agents_md
            assert_that(agents_md, contains_string("# Agents\n\nSell well.\n\n" + START_MARKER))
            assert_that(agents_md, contains_string("- Use Vilnius time for dates and deadlines.\n"))
            assert_that(agents_md, contains_string("- Ask for approval before changing records.\n"))

        with then("the published version is unchanged"):
            with Session(context.postgres_delegate.engine) as session:
                published = session.exec(select(AgentTemplate).where(AgentTemplate.template_key == "sales")).one()
            assert_that(published.agents_md, equal_to("# Agents\n\nSell well.\n"))


def test_rules_already_in_the_section_are_not_added_twice():
    with given(playbooks_api_setup(there_is_a_template(template_key="sales"))) as context:
        _add(context, RULES[:1])
        with when("the same rule, differently cased, is added with a new one"):
            response = _add(context, ["use vilnius time for dates and deadlines", RULES[1]])

        with then("only the new rule is added"):
            assert_that(response.json(), has_entries(added=1, already_present=1))
            assert_that(_draft(context).agents_md.lower().count("vilnius"), equal_to(1))


def test_an_existing_draft_keeps_its_edits_and_required_skills():
    with given(
        playbooks_api_setup(
            there_is_a_template(template_key="sales"),
            there_is_an_org_template_draft(
                template_key="sales", agents_md="# Unpublished edits\n", soul_md="Draft soul"
            ),
            there_is_a_skill(name="CRM"),
            there_is_an_org_template_draft_skill(),
        )
    ) as context:
        with when("rules are added to the Template"):
            _add(context)

        with then("they join the person's draft without touching its other content or requirements"):
            draft = _draft(context)
            assert_that(draft.agents_md, contains_string("# Unpublished edits\n\n" + START_MARKER))
            assert_that(draft.soul_md, equal_to("Draft soul"))
            with Session(context.postgres_delegate.engine) as session:
                skills = session.exec(
                    select(AgentTemplateDraftSkill.skill_id).where(AgentTemplateDraftSkill.draft_id == draft.id)
                ).all()
            assert_that(skills, contains_exactly(context.skill.id))


def test_a_draft_with_broken_section_markers_is_left_for_a_person_to_fix():
    with given(
        playbooks_api_setup(
            there_is_a_template(template_key="sales"),
            there_is_an_org_template_draft(template_key="sales", agents_md=f"{START_MARKER}\n- Old rule\n"),
        )
    ) as context:
        with when("rules are added"):
            response = _add(context)

        with then("the request conflicts and the draft is unchanged"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(_draft(context).agents_md, is_not(contains_string("Vilnius")))


def test_members_cannot_add_conventions():
    with given(
        playbooks_api_setup(there_is_a_template(template_key="sales"), signed_in_as(OrganizationRole.MEMBER))
    ) as context:
        with when("a Member adds rules"):
            response = _add(context)

        with then("it is forbidden and no draft is started"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(AgentTemplateDraft)).all(), equal_to([]))


def test_an_unknown_template_is_not_found():
    with given(playbooks_api_setup()) as context:
        with when("rules are added to a Template that does not exist"):
            response = _add(context, template_key="missing")

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_the_rule_list_is_bounded():
    with given(playbooks_api_setup(there_is_a_template(template_key="sales"))) as context:
        with when("no rules, then 31 rules, are sent"):
            empty = _add(context, [])
            too_many = _add(context, [f"Rule {i}" for i in range(31)])

        with then("both are rejected"):
            assert_that(empty.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(too_many.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
