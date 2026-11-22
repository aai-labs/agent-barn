import anyio.to_thread
from hamcrest import assert_that, equal_to
from starlette.testclient import TestClient

from api.core.config import get_config
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
                assert_that(response.json(), equal_to({"status": "ok", "db": "connected"}))


def test_sync_routes_run_on_the_configured_thread_pool():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            database_repo_is_ready(),
            database_is_clean(),
        ]
    ) as context:
        app = context.app

        @app.get("/__test/thread-limit")
        async def thread_limit():
            # On the event loop itself: the limiter every sync route's thread is drawn from.
            return {"total_tokens": anyio.to_thread.current_default_thread_limiter().total_tokens}

        with when("the app starts up and serves a request"), TestClient(app) as client:
            response = client.get("/__test/thread-limit")

        with then("that route runs on a pool of API_THREAD_LIMIT threads, not AnyIO's 40"):
            assert_that(response.json()["total_tokens"], equal_to(get_config().api_thread_limit))
