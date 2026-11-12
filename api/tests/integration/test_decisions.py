import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_length
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agents.repository import AgentRepository
from api.domains.decisions.models import PlatformDecisionSettings
from api.domains.decisions.service import DecisionService
from api.domains.events.models import OutboxMessage
from api.infrastructure.litellm.decisions import DecisionError, DecisionFailure, YesNoQuestion
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent import FAKE_LITELLM_KEY, there_is_an_agent
from api.tests.steps.decisions import (
    a_platform_admin_without_membership,
    decisions_api_setup,
    the_decision_model_answers,
)

BASE = "/api/v1/platform/settings/decisions"
JEV = "openrouter/typesafe/jev-1.14"
OPENAI = "openrouter/openai/gpt-6-luna-decisions"
QUESTIONS = {"q": YesNoQuestion("Is this unusual?")}


def _auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _changed_events(context):
    with Session(context.postgres_delegate.engine) as session:
        return session.exec(
            select(OutboxMessage).where(OutboxMessage.event_name == "platform.decision_model.changed")
        ).all()


def _decide(context, **options):
    return context.injector.get(DecisionService).decide(context.agent.id, {"ratio": 3.2}, QUESTIONS, **options)


# --- the Platform setting ---------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,payload",
    [("GET", "", None), ("GET", "/models", None), ("PUT", "", {"model": "openai"})],
)
def test_an_organization_owner_cannot_manage_the_platform_decision_model(method, path, payload):
    with given(decisions_api_setup()) as context:
        with when("an Organization Owner calls the Platform setting"):
            response = context.client.request(method, BASE + path, headers=_auth(context), json=payload)

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_the_deployment_default_applies_until_a_model_is_chosen():
    with given(decisions_api_setup(a_platform_admin_without_membership())) as context:
        with when("a Platform Administrator reads the setting"):
            response = context.client.get(BASE, headers=_auth(context))

        with then("the deployment default is reported with no change time"):
            assert_that(response.json(), has_entries(model="jev", updated_at=None))


def test_the_choices_are_the_configured_decision_models():
    with given(decisions_api_setup(a_platform_admin_without_membership())) as context:
        with when("a Platform Administrator lists the models"):
            response = context.client.get(BASE + "/models", headers=_auth(context))

        with then("each configured name is offered"):
            assert_that([item["value"] for item in response.json()], contains_exactly("jev", "openai"))


def test_choosing_a_model_persists_it_with_one_audit_event():
    with given(decisions_api_setup(a_platform_admin_without_membership())) as context:
        with when("a Platform Administrator saves the same new model twice"):
            first = context.client.put(BASE, headers=_auth(context), json={"model": "openai"})
            context.client.put(BASE, headers=_auth(context), json={"model": "openai"})

        with then("the choice is stored once and audited once"):
            assert_that(first.status_code, equal_to(status.HTTP_200_OK))
            with Session(context.postgres_delegate.engine) as session:
                row = session.get(PlatformDecisionSettings, 1)
            assert row is not None
            assert_that(row.model, equal_to("openai"))
            events = _changed_events(context)
            assert_that(events, has_length(1))
            assert_that(events[0].payload, has_entries(previous="jev", current="openai"))


@pytest.mark.parametrize("model", ["gemini", JEV, ""])
def test_models_that_are_not_configured_are_refused(model):
    with given(decisions_api_setup(a_platform_admin_without_membership())) as context:
        with when("a Platform Administrator saves a model that is not configured"):
            response = context.client.put(BASE, headers=_auth(context), json={"model": model})

        with then("it is refused and nothing changes"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))
            assert_that(_changed_events(context), has_length(0))


# --- asking a decision ------------------------------------------------------------------


def test_a_decision_uses_the_platform_model_and_bills_the_agent_key():
    with given(decisions_api_setup(there_is_an_agent(), the_decision_model_answers())) as context:
        with when("a feature asks a decision for an Agent"):
            result = _decide(context)

        with then("the Agent's own key and the default model's slug are used"):
            assert_that(result.answers["q"].probability, equal_to(0.9))
            context.decide.assert_called_once_with(FAKE_LITELLM_KEY, JEV, {"ratio": 3.2}, QUESTIONS)


def test_the_saved_platform_choice_applies_to_later_decisions():
    with given(
        decisions_api_setup(a_platform_admin_without_membership(), there_is_an_agent(), the_decision_model_answers())
    ) as context:
        with when("a Platform Administrator switches to OpenAI and a feature then asks a decision"):
            context.client.put(BASE, headers=_auth(context), json={"model": "openai"})
            _decide(context)

        with then("the OpenAI slug is used"):
            assert_that(context.decide.call_args.args[1], equal_to(OPENAI))


def test_a_caller_can_override_the_platform_model_for_one_call():
    with given(decisions_api_setup(there_is_an_agent(), the_decision_model_answers())) as context:
        with when("a feature asks a decision with an explicit model"):
            _decide(context, model="openai")

        with then("that model's slug is used"):
            assert_that(context.decide.call_args.args[1], equal_to(OPENAI))


def test_an_unknown_override_is_a_programming_error():
    with given(decisions_api_setup(there_is_an_agent(), the_decision_model_answers())) as context:
        with when("a feature names a model that is not configured"):
            with pytest.raises(ValueError):
                _decide(context, model="gemini")

        with then("no call is made"):
            context.decide.assert_not_called()


def test_slugs_come_from_configuration():
    env = {"DECISION_MODELS": '{"jev": "openrouter/typesafe/jev-1.15", "openai": "openrouter/openai/x"}'}
    with given(decisions_api_setup(there_is_an_agent(), the_decision_model_answers(), env=env)) as context:
        with when("a feature asks a decision after a jev version bump in configuration"):
            _decide(context)

        with then("the new slug is used"):
            assert_that(context.decide.call_args.args[1], equal_to("openrouter/typesafe/jev-1.15"))


@pytest.mark.parametrize("deleted", [True, False])
def test_an_agent_without_a_usable_key_cannot_be_billed(deleted):
    with given(decisions_api_setup(there_is_an_agent(deleted=deleted), the_decision_model_answers())) as context:
        if not deleted:
            context.agent.litellm_key_encrypted = ""
            context.injector.get(AgentRepository).save(context.agent)

        with when("a feature asks a decision for it"):
            with pytest.raises(DecisionError) as raised:
                _decide(context)

        with then("it is rejected without a call"):
            assert_that(raised.value.failure, equal_to(DecisionFailure.KEY_OR_MODEL_REJECTED))
            context.decide.assert_not_called()


def test_an_agent_whose_key_cannot_be_decrypted_cannot_be_billed():
    with given(decisions_api_setup(there_is_an_agent(), the_decision_model_answers())) as context:
        context.agent.litellm_key_encrypted = "not-a-fernet-token"
        context.injector.get(AgentRepository).save(context.agent)

        with when("a feature asks a decision for it"):
            with pytest.raises(DecisionError) as raised:
                _decide(context)

        with then("it is rejected without a call"):
            assert_that(raised.value.failure, equal_to(DecisionFailure.KEY_OR_MODEL_REJECTED))
            context.decide.assert_not_called()


def test_without_a_proxy_decisions_are_unavailable():
    with given(
        decisions_api_setup(there_is_an_agent(), the_decision_model_answers(), env={"LITELLM_BASE_URL": ""})
    ) as context:
        with when("a feature asks a decision"):
            with pytest.raises(DecisionError) as raised:
                _decide(context)

        with then("it is unavailable without a call"):
            assert_that(raised.value.failure, equal_to(DecisionFailure.UNAVAILABLE))
            context.decide.assert_not_called()


def test_a_saved_choice_no_longer_configured_falls_back_to_the_default():
    with given(
        decisions_api_setup(a_platform_admin_without_membership(), there_is_an_agent(), the_decision_model_answers())
    ) as context:
        context.client.put(BASE, headers=_auth(context), json={"model": "openai"})
        context.injector.get(Config).decision_models = {"jev": JEV}

        with when("a feature asks a decision after OpenAI is removed from configuration"):
            _decide(context)

        with then("the deployment default answers"):
            assert_that(context.decide.call_args.args[1], equal_to(JEV))
