from types import SimpleNamespace
from typing import cast

import anyio
import anyio.to_thread
from hamcrest import assert_that, equal_to

from api.api_app import apply_thread_limit
from api.core.config import Config
from api.tests.core.givenpy import then, when


def test_apply_thread_limit_sizes_the_running_loops_thread_pool():
    async def apply_and_read() -> float:
        apply_thread_limit(cast(Config, SimpleNamespace(api_thread_limit=73)))
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    with when("the limit is applied inside the event loop"):
        tokens = anyio.run(apply_and_read)

        with then("sync work on that loop may use that many threads"):
            assert_that(tokens, equal_to(73))


def test_the_api_defaults_to_100_threads():
    assert_that(Config.model_fields["api_thread_limit"].default, equal_to(100))
