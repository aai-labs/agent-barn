from hamcrest import assert_that, equal_to
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready


def test_api_health_is_ok():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I request the health endpoint"):
            response = client.get("/api/v1/health")

            with then("it should return OK"):
                assert_that(response.status_code, equal_to(200))
                assert_that(
                    response.json(), equal_to({"status": "ok", "db": "connected"})
                )
