"""Agent Settings: the Organization-scoped default runtime model (AF-225).

The contract under test is three rules:

- an Agent with an empty `model` runs the Organization's default, and an
  Organization without its own default runs the platform's;
- an Organization's own default must stay inside its model allowlist, enforced both
  when the default is set and when the allowlist is edited;
- an Organization that follows the platform default cannot police it, so an Agent
  inheriting that value still starts.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, empty, equal_to, is_not, none

from api.domains.agents.models import AgentStatus
from api.domains.events.catalog import ORGANIZATION_AGENT_SETTINGS_CHANGED
from api.domains.events.models import OutboxMessage
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

# The install-wide floor every Organization follows until it picks its own default.
PLATFORM_DEFAULT = "litellm/gpt-5-mini"

_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
        "AGENT_DEFAULT_MODEL": PLATFORM_DEFAULT,
        "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        "API_EXTERNAL_URL": "https://api.test.com",
        "SKIP_SLACK_TOKEN_VALIDATION": "true",
    }
)

_SETTINGS = "/api/v1/organizations/{organization_id}/agent-settings"
_AGENTS = "/api/v1/organizations/{organization_id}/agents"


def _given(allowed_models: list[str] | None = None, role: OrganizationRole = OrganizationRole.OWNER):
    return [
        _ENV,
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(role=role, allowed_models=allowed_models),
        use_org_for_auth(),
        there_is_a_template(),
    ]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _outbox_messages(context) -> list[OutboxMessage]:
    return context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)


@contextmanager
def catalog_contains(*model_ids: str) -> Iterator[MagicMock]:
    """Stands in for the OpenRouter catalogue a candidate default is checked against."""
    with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as list_models:
        list_models.return_value = [{"id": model_id, "name": model_id} for model_id in model_ids]
        yield list_models


def _set_default(context, model: str | None, headers: dict | None = None):
    return context.client.put(
        _SETTINGS,
        json={"default_model": model},
        headers=headers or _auth(context),
    )


def test_a_new_organization_follows_the_platform_default():
    with given(_given()) as context:
        with when("I read Agent Settings for an Organization that has never set them"):
            response = context.client.get(_SETTINGS, headers=_auth(context))

        with then("the platform default is reported, with no Organization choice of its own"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["default_model"], none())
            assert_that(body["effective_default_model"], equal_to(PLATFORM_DEFAULT))
            assert_that(body["default_model_source"], equal_to("platform"))
            assert_that(body["updated_at"], none())


def test_agent_settings_require_authentication():
    with given(_given()) as context:
        with when("an unauthenticated caller reads or changes Agent Settings"):
            read = context.client.get(_SETTINGS)
            write = context.client.put(_SETTINGS, json={"default_model": PLATFORM_DEFAULT})

        with then("both routes reject the request"):
            assert_that(read.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(write.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_setting_a_default_reports_it_as_the_organizations_own():
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("openai/gpt-5-mini", "qwen/qwen3.6-plus"):
            with when("the owner picks a default model"):
                response = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("it becomes the Organization's own default"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["default_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(body["effective_default_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(body["default_model_source"], equal_to("organization"))
                assert_that(body["updated_at"], is_not(none()))


def test_reverting_to_null_follows_the_platform_default_again():
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("the owner clears the Organization's default"):
                response = _set_default(context, None)

            with then("the Organization follows the platform default again"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["default_model"], none())
                assert_that(body["effective_default_model"], equal_to(PLATFORM_DEFAULT))
                assert_that(body["default_model_source"], equal_to("platform"))


def test_counts_split_inheriting_agents_from_overrides():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        there_is_an_agent(
            name="Pinned Agent",
            model="litellm/openrouter/qwen/qwen3.6-plus",
            bot_token="xoxb-second-agent-token",
        )(context)

        with when("I read Agent Settings"):
            response = context.client.get(_SETTINGS, headers=_auth(context))

        with then("the two Agents are counted by where their model comes from"):
            body = response.json()
            assert_that(body["inheriting_agent_count"], equal_to(1))
            assert_that(body["override_agent_count"], equal_to(1))


def test_a_member_cannot_read_or_write_agent_settings():
    member_id = uuid7()
    with given(_given(allowed_models=["*"])) as context:
        there_is_a_user(
            id=member_id,
            email="member-agent-settings@example.com",
            organization_id=context.organization.id,
            role=OrganizationRole.MEMBER,
        )(context)
        there_is_an_access_token_for_user(user_id=member_id)(context)
        member_headers = {"Authorization": f"Bearer {context.access_token}"}

        with when("a plain Member reaches Agent Settings"):
            read = context.client.get(_SETTINGS, headers=member_headers)
            write = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus", headers=member_headers)

        with then("both are refused — managing Agent defaults is an Organization admin capability"):
            assert_that(read.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(write.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- R3a: the default is picked from the allowlist ---------------------------------


def test_a_default_outside_the_allowlist_is_rejected():
    with given(_given(allowed_models=["qwen/*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            with when("the owner picks a model the Organization does not allow"):
                response = _set_default(context, "litellm/openrouter/openai/gpt-5-mini")

            with then("it is refused and the message points at Allowed Models"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
                assert_that(response.json()["detail"], contains_string("not in the organization's allowed model list"))
                assert_that(response.json()["detail"], contains_string("Allowed Models"))


def test_a_default_inside_the_allowlist_is_accepted():
    with given(_given(allowed_models=["qwen/*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            with when("the owner picks a model the Organization allows"):
                response = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("it is accepted"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_a_wildcard_allowlist_still_rejects_a_model_that_does_not_exist():
    """The allowlist holds globs, so `["*"]` permits any string. The catalogue check
    is what stops a default that no provider actually serves."""
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            with when("the owner picks a model absent from the catalogue"):
                response = _set_default(context, "litellm/openrouter/acme/not-a-real-model")

            with then("it is refused even though the allowlist would permit it"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
                assert_that(response.json()["detail"], contains_string("does not match any known models"))


def test_an_unreachable_catalogue_does_not_block_setting_a_default():
    """The catalogue check is advisory: an OpenRouter outage must not stop an owner
    from managing their own settings, matching how the allowlist editor degrades."""
    with given(_given(allowed_models=["*"])) as context:
        with patch("api.infrastructure.openrouter.client.OpenRouterClient.list_models") as list_models:
            list_models.side_effect = RuntimeError("OpenRouter unreachable")

            with when("the owner picks a default while the catalogue is down"):
                response = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("the save goes through"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(response.json()["default_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))


# --- R3b: the default cannot be removed from the allowlist -------------------------


def test_the_allowlist_cannot_drop_the_organizations_default():
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("the owner narrows the allowlist so it no longer covers the default"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("the edit is refused and names the default"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
                assert_that(response.json()["detail"], contains_string("default Agent model"))
                assert_that(response.json()["detail"], contains_string("qwen/qwen3.6-plus"))


def test_the_allowlist_may_drop_the_platform_default_when_the_organization_tracks_it():
    """An Organization that never set its own default has nothing to protect: the
    platform value can change without any request to this API."""
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("openai/gpt-5-mini"):
            with when("the owner narrows the allowlist while following the platform default"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("the edit is accepted"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_the_allowlist_cannot_strand_an_agent_pinned_to_a_removed_model():
    """Removing the model would not migrate the Agent — it would only make it
    unstartable, and not until someone next restarted it."""
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(name="Scribe", model="litellm/openrouter/qwen/qwen3.6-plus"),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            with when("the owner removes a model an Agent is pinned to"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("the edit is refused and names the Agent standing in the way"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
                detail = response.json()["detail"]
                assert_that(detail, contains_string("Scribe"))
                assert_that(detail, contains_string("qwen/qwen3.6-plus"))
                assert_that(detail, contains_string("1 Agent is"))


def test_the_refusal_names_every_stranded_agent():
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(name="Scribe", model="litellm/openrouter/qwen/qwen3.6-plus"),
            there_is_an_agent(name="Herald", model="litellm/openrouter/qwen/qwen3.6-plus"),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            with when("the owner removes the model both Agents are pinned to"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("both Agents are named"):
                detail = response.json()["detail"]
                assert_that(detail, contains_string("2 Agents are"))
                assert_that(detail, contains_string("Herald and Scribe"))


def test_an_inheriting_agent_never_blocks_an_allowlist_edit():
    """Inheriting Agents follow the default, which its own guard protects."""
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("openai/gpt-5-mini"):
            with when("the owner narrows the allowlist"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("the edit is accepted"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_an_allowlist_edit_that_keeps_every_pinned_model_is_accepted():
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(name="Scribe", model="litellm/openrouter/qwen/qwen3.6-plus"),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            with when("the owner narrows the allowlist but keeps the pinned model"):
                response = context.client.patch(
                    f"/api/v1/organizations/{context.organization.id}",
                    json={"allowed_models": ["qwen/qwen3.6-plus", "openai/gpt-5-mini"]},
                    headers=_auth(context),
                )

            with then("the edit is accepted"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))


# --- R1/R4: what an Agent actually starts on --------------------------------------


def _started_overlay_model(context) -> str:
    k8s: MagicMock = context.injector.get(KubernetesClient)
    config_map = k8s.create_config_map.call_args.args[1]
    overlay = json.loads(config_map.data["openclaw-config-overlay.json"])
    return overlay["agents"]["defaults"]["model"]["primary"]


def test_an_inheriting_agent_starts_on_the_organizations_default():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("I start the inheriting Agent"):
                response = context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context))

            with then("the runtime is pointed at the Organization's default"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(_started_overlay_model(context), equal_to("litellm/openrouter/qwen/qwen3.6-plus"))


def test_an_agent_with_its_own_model_ignores_the_organizations_default():
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(model="litellm/openrouter/openai/gpt-5-mini"),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("I start the Agent that pins its own model"):
                response = context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context))

            with then("its own model is preserved"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                assert_that(_started_overlay_model(context), equal_to("litellm/openrouter/openai/gpt-5-mini"))


def test_an_inheriting_agent_starts_when_the_platform_default_is_outside_the_allowlist():
    """The AF-225 regression: before this, changing AGENT_DEFAULT_MODEL broke starts
    for every Agent in an Organization whose allowlist predated the change."""
    with given([*_given(allowed_models=["qwen/*"]), there_is_an_agent(model="")]) as context:
        with when("I start an inheriting Agent whose platform default the allowlist excludes"):
            response = context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context))

        with then("it starts on the platform default"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_started_overlay_model(context), equal_to(PLATFORM_DEFAULT))


# --- running vs pending: what an Agent is serving right now ------------------------
#
# Every assertion below re-reads the Agent over HTTP rather than trusting the body the
# start/stop call returned. The lifecycle save copies an allowlist of fields onto a
# freshly locked row, so a field can be set in memory, returned correctly, and still
# never reach the database — which is exactly the bug these tests exist to catch.


def _read_agent(context) -> dict:
    response = context.client.get(f"{_AGENTS}/{context.agent.id}", headers=_auth(context))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    return response.json()


def _start(context):
    return context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context))


def _stop(context):
    return context.client.post(f"{_AGENTS}/{context.agent.id}/stop", headers=_auth(context))


def test_starting_an_agent_records_the_model_its_pod_was_started_on():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("I start an inheriting Agent"):
                assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

            with then("the model it started on is persisted, with nothing pending"):
                agent = _read_agent(context)
                assert_that(agent["running_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(agent["effective_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(agent["pending_model"], equal_to(""))


def test_stopping_an_agent_clears_the_recorded_running_model():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

        with when("I stop it again"):
            assert_that(_stop(context).status_code, equal_to(status.HTTP_200_OK))

        with then("nothing is recorded as running"):
            agent = _read_agent(context)
            assert_that(agent["running_model"], equal_to(""))
            assert_that(agent["pending_model"], equal_to(""))


def test_a_running_agent_keeps_reporting_the_model_it_started_on():
    """The runtime reads its model once at container start, so a default change does not
    reach a running Agent. Reporting the freshly resolved value as current would claim a
    model the pod is not serving."""
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")
            assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

            with when("the Organization changes its default underneath the running Agent"):
                _set_default(context, "litellm/openrouter/openai/gpt-5-mini")

            with then("it still reports the old model, and names the switch a restart would make"):
                agent = _read_agent(context)
                assert_that(agent["running_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(agent["effective_model"], equal_to("litellm/openrouter/openai/gpt-5-mini"))
                assert_that(agent["pending_model"], equal_to("litellm/openrouter/openai/gpt-5-mini"))


def test_a_pinned_agent_reports_nothing_pending_when_the_default_moves():
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(model="litellm/openrouter/openai/gpt-5-mini"),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

            with when("the Organization changes its default"):
                _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("the Agent that pins its own model is untouched"):
                agent = _read_agent(context)
                assert_that(agent["running_model"], equal_to("litellm/openrouter/openai/gpt-5-mini"))
                assert_that(agent["effective_model"], equal_to("litellm/openrouter/openai/gpt-5-mini"))
                assert_that(agent["pending_model"], equal_to(""))


def test_restarting_adopts_the_new_default_and_clears_the_pending_switch():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")
            assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))
            _set_default(context, "litellm/openrouter/openai/gpt-5-mini")

            with when("the Agent is restarted"):
                assert_that(_stop(context).status_code, equal_to(status.HTTP_200_OK))
                assert_that(_start(context).status_code, equal_to(status.HTTP_200_OK))

            with then("it is running the new default and nothing is pending"):
                agent = _read_agent(context)
                assert_that(agent["running_model"], equal_to("litellm/openrouter/openai/gpt-5-mini"))
                assert_that(agent["pending_model"], equal_to(""))
                assert_that(_started_overlay_model(context), equal_to("litellm/openrouter/openai/gpt-5-mini"))


def test_an_agent_pinning_a_disallowed_model_still_fails_to_start():
    """The allowlist keeps its job for the choices a user actually made."""
    with given(
        [
            *_given(allowed_models=["qwen/*"]),
            there_is_an_agent(model="litellm/openrouter/openai/gpt-5-mini"),
        ]
    ) as context:
        with when("I start an Agent pinned to a model the Organization no longer allows"):
            response = context.client.post(f"{_AGENTS}/{context.agent.id}/start", headers=_auth(context))

        with then("the start is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(
                response.json()["detail"], contains_string("no longer in the organization's allowed model list")
            )


# --- the Agent read contract ------------------------------------------------------


def test_agent_read_names_where_its_model_comes_from():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("I read an inheriting Agent"):
                response = context.client.get(f"{_AGENTS}/{context.agent.id}", headers=_auth(context))

            with then("it reports inheritance and resolves the model it will run"):
                body = response.json()
                assert_that(body["model"], equal_to(""))
                assert_that(body["model_source"], equal_to("default"))
                assert_that(body["effective_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))


def test_clearing_an_agents_model_returns_it_to_the_default():
    with given(
        [
            *_given(allowed_models=["*"]),
            there_is_an_agent(model="litellm/openrouter/openai/gpt-5-mini", status=AgentStatus.STOPPED),
        ]
    ) as context:
        with catalog_contains("qwen/qwen3.6-plus", "openai/gpt-5-mini"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with when("the Agent's model is cleared"):
                response = context.client.patch(
                    f"{_AGENTS}/{context.agent.id}",
                    json={"model": None},
                    headers=_auth(context),
                )

            with then("it follows the Organization's default again"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["model"], equal_to(""))
                assert_that(body["model_source"], equal_to("default"))
                assert_that(body["effective_model"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))


# --- audit ------------------------------------------------------------------------


def test_a_default_change_is_recorded_once_with_its_blast_radius():
    with given([*_given(allowed_models=["*"]), there_is_an_agent(model="")]) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            with when("the owner changes the default"):
                response = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("exactly one change Event is staged, carrying the transition and the count"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                messages = [m for m in _outbox_messages(context) if m.event_name == ORGANIZATION_AGENT_SETTINGS_CHANGED]
                assert_that(len(messages), equal_to(1))
                payload = messages[0].payload
                assert_that(payload["setting"], equal_to("default_model"))
                assert_that(payload["previous"], none())
                assert_that(payload["current"], equal_to("litellm/openrouter/qwen/qwen3.6-plus"))
                assert_that(payload["inheriting_agent_count"], equal_to(1))
                assert_that(payload["actor_display"], is_not(empty()))


def test_resaving_the_same_default_records_nothing():
    with given(_given(allowed_models=["*"])) as context:
        with catalog_contains("qwen/qwen3.6-plus"):
            _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")
            before = len([m for m in _outbox_messages(context) if m.event_name == ORGANIZATION_AGENT_SETTINGS_CHANGED])

            with when("the owner saves the same default again"):
                response = _set_default(context, "litellm/openrouter/qwen/qwen3.6-plus")

            with then("no second Event is staged — an audit trail of unchanged values is noise"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                after = len(
                    [m for m in _outbox_messages(context) if m.event_name == ORGANIZATION_AGENT_SETTINGS_CHANGED]
                )
                assert_that(after, equal_to(before))


def test_agent_settings_are_concealed_for_another_organization():
    other_org = uuid7()
    with given(_given(allowed_models=["*"])) as context:
        organization_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        assert_that(organization_repository.get(other_org), none())

        with when("the owner asks for another Organization's Agent Settings"):
            response = context.client.get(
                f"/api/v1/organizations/{other_org}/agent-settings",
                headers=_auth(context),
            )

        with then("the request is refused rather than answered"):
            assert_that(
                response.status_code,
                equal_to(status.HTTP_403_FORBIDDEN),
            )
