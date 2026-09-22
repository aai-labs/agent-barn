"""The API-edge webhook route (`runtime_webhook_routes.py`), reached through a webhook
connection that falls through Teams' runtime-owned relay to the Communications proxy.

Teams' runtime gateway added a route on the public-facing API app that matches the same
`/{connection_id}` pattern a signed webhook call hits. A webhook caller signs its body and
sends no Authorization header at all, so that header must stay optional here too -- the
same fix already applied to the Communications-side route in `gateway_routes.py`.
"""

from typing import Any
from unittest.mock import patch

import httpx
from fastapi import status
from hamcrest import assert_that, equal_to

from api.domains.agents.models import AgentStatus
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
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

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
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.RUNNING),
]


def _create_webhook_connection(context) -> dict[str, Any]:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={"platform_key": "webhook", "display_name": "CI pipeline", "credentials": {}},
        headers={"Authorization": f"Bearer {context.access_token}"},
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()


def test_a_signed_webhook_call_without_an_authorization_header_is_not_rejected_at_the_edge() -> None:
    """This used to 422 here even though the webhook plugin never requires the header --
    a later, unrelated route (Teams' runtime relay) required it for every connection,
    webhook included, because it sits in front of the plugin's own verification."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("a signed request with no Authorization header reaches the API edge"):
            upstream = httpx.Response(
                status.HTTP_202_ACCEPTED,
                headers={"Content-Type": "application/json"},
                content=b'{"accepted": []}',
            )
            with patch(
                "api.domains.communications.runtime_webhook_routes.resilient_request",
                return_value=upstream,
            ) as proxy:
                response = context.client.post(
                    f"/communications/v1/webhooks/{connection['id']}",
                    json={"event_id": "evt-1", "prompt": "Write release notes."},
                )

        with then("it is not rejected for a missing header -- it reaches the proxy fallback"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            proxy.assert_called_once()
