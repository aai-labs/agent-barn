"""A failed start has to reach the person who asked for it.

Agent Farm recorded a useful `last_error` on the Agent and answered the request with
`Failed to start agent <uuid>`, so the only way to learn that a namespace was out of
storage quota was to query the database or the cluster. These tests hold the
contract that replaced that: the failure is classified, sanitized, returned to the
caller, and still readable on the Agent afterwards.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, status
from hamcrest import assert_that, contains_string, equal_to, is_, is_not, none
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.infrastructure.kubernetes.client import KubernetesClient
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
    there_is_an_agent_in_another_org,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template

_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]

# A PVC rejection in the shape Kubernetes reports it.
_QUOTA_MESSAGE = (
    'persistentvolumeclaims "agent-6f1c9e52-2b47-4c8a-9d1e-3f5b7c0a4e21" is forbidden: '
    "exceeded quota: example-quota, requested: requests.storage=1Gi, "
    "used: requests.storage=30Gi, limited: requests.storage=30Gi"
)


class _ApiException(Exception):
    """Stands in for kubernetes.client.ApiException, which carries status + body."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status = status_code
        self.body = json.dumps({"kind": "Status", "status": "Failure", "message": message, "code": status_code})


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _quota_exhausted_namespace(context) -> MagicMock:
    k8s: Any = context.injector.get(KubernetesClient)
    k8s.create_pvc.side_effect = _ApiException(403, _QUOTA_MESSAGE)
    return k8s


def test_a_quota_rejection_reaches_the_caller_that_asked_for_the_start() -> None:
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        _quota_exhausted_namespace(context)

        with when("I start an agent whose namespace is out of storage quota"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the response says the cluster cannot serve the request right now"):
            assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))

        with then("it names the failure, the exhausted axis, and who can clear it"):
            detail = response.json()["detail"]
            assert_that(detail["code"], equal_to("QUOTA_EXHAUSTED"))
            assert_that(detail["summary"].casefold(), contains_string("quota"))
            assert_that(detail["detail"], contains_string("requests.storage"))

        with then("no part of the raw cluster rejection is echoed back"):
            assert_that(response.text, is_not(contains_string("is forbidden")))
            assert_that(response.text, is_not(contains_string("agent-6f1c9e52")))


def test_a_failed_start_stays_readable_on_the_agent_after_the_response_is_gone() -> None:
    """The banner has to survive navigation and refresh, so the failure belongs on the
    Agent, not only in the response that reported it."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        _quota_exhausted_namespace(context)

        with when("the start fails and I load the agent again"):
            client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))
            response = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        with then("the agent reports ERROR and carries the same classified failure"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(body["last_error"]["code"], equal_to("QUOTA_EXHAUSTED"))
            assert_that(body["last_error"]["detail"], contains_string("requests.storage"))

        with then("reading it again is stable rather than a one-shot"):
            again = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))
            assert_that(again.json()["last_error"]["code"], equal_to("QUOTA_EXHAUSTED"))


def test_a_successful_start_clears_the_previous_failure() -> None:
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        k8s = _quota_exhausted_namespace(context)

        with when("a failed start is followed by one the cluster accepts"):
            client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))
            k8s.create_pvc.side_effect = None
            started = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("the agent is running and reports no failure"):
            assert_that(started.status_code, equal_to(status.HTTP_200_OK))
            assert_that(started.json()["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(started.json()["last_error"], is_(none()))

        with then("the cleared state is what a later read sees too"):
            reloaded = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))
            assert_that(reloaded.json()["last_error"], is_(none()))


def test_a_failure_before_the_cluster_calls_is_recorded_the_same_way() -> None:
    """The old handler wrapped only Kubernetes resource creation, so anything that
    broke earlier in provisioning surfaced as an unexplained 500 and left the Agent
    looking untouched."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("building the agent's Service fails before any cluster call"):
            with patch(
                "api.domains.agents.service.build_service",
                side_effect=ValueError("builder produced an unusable manifest"),
            ):
                response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it is reported as an unclassified provisioning failure"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            assert_that(response.json()["detail"]["code"], equal_to("PROVISIONING_FAILED"))

        with then("the builder's own message is not what the user is shown"):
            assert_that(response.text, is_not(contains_string("unusable manifest")))

        with then("the agent records the failure rather than appearing untouched"):
            body = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))
            assert_that(body["last_error"]["code"], equal_to("PROVISIONING_FAILED"))


def test_an_http_error_that_is_not_a_declared_precondition_is_still_recorded() -> None:
    """Exemption is a decision at the raise site, not a property of being an
    HTTPException. A `raise HTTPException(...)` added mid-provisioning must not
    quietly opt itself out of being recorded on the Agent."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("provisioning raises an HTTPException that declares no precondition"):
            with patch(
                "api.domains.agents.service.build_service",
                side_effect=HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT, detail="brewing"),
            ):
                response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it is classified rather than passed through untouched"):
            assert_that(response.status_code, equal_to(status.HTTP_500_INTERNAL_SERVER_ERROR))
            assert_that(response.json()["detail"]["code"], equal_to("PROVISIONING_FAILED"))

        with then("and the agent records it"):
            body = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.ERROR.value))


def test_a_precondition_failure_is_not_recorded_as_a_provisioning_failure() -> None:
    """Starting an Agent that is already running is an answer to the request, not
    evidence that provisioning broke, so it must not push the Agent into ERROR."""
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        with when("I start an agent that is already running"):
            response = client.post(f"{_BASE}/{context.agent.id}/start", headers=_auth(context))

        with then("it stays a conflict and the agent keeps running with no error"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            body = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert_that(body["status"], equal_to(AgentStatus.RUNNING.value))
            assert_that(body["last_error"], is_(none()))


def test_a_failure_on_an_inaccessible_agent_is_not_readable_across_organizations() -> None:
    with given([*_GIVEN, there_is_an_agent_in_another_org()]) as context:
        client: TestClient = context.client
        other_agent_id = context.other_org_agent.id

        with when("I try to start and then read an agent in another organization"):
            start = client.post(f"{_BASE}/{other_agent_id}/start", headers=_auth(context))
            read = client.get(f"{_BASE}/{other_agent_id}", headers=_auth(context))

        with then("both are hidden, and no provisioning error is disclosed"):
            assert_that(start.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(read.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(read.text, is_not(contains_string("last_error")))
