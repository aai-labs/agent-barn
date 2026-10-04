from hamcrest import assert_that, contains_string, equal_to, has_entries, has_length

from api.tests.core.givenpy import given, then, when
from api.tests.helpers.hindsight_cost_bridge import hindsight_cost_boundary_is_ready, run_hindsight_cost_driver


def test_bank_identity_survives_concurrent_foreground_and_background_model_calls():
    with given([hindsight_cost_boundary_is_ready()]) as context:
        with when("the pinned Hindsight provider runs concurrent bank operations"):
            run_hindsight_cost_driver(context)
        with then("the real model consumer completes successfully"):
            assert_that(context.completed.returncode, equal_to(0), context.completed.stdout + context.completed.stderr)
            assert_that(context.completed.stdout, contains_string("HINDSIGHT_COST_CONTRACT=ok"))
        with then("each call carries its own bank rather than another concurrent bank"):
            assert_that(context.model_requests, has_length(4))
            actual = {request["messages"][0]["content"]: request.get("user") for request in context.model_requests}
            assert_that(
                actual,
                has_entries(
                    retain="org-11111111-2222-3333-4444-555555555555",
                    reflect="org-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    consolidation="org-11111111-2222-3333-4444-555555555555",
                    startup=None,
                ),
            )


def test_platform_model_changes_reach_new_hindsight_calls_without_changing_in_flight_operations():
    with given([hindsight_cost_boundary_is_ready()]) as context:
        run_hindsight_cost_driver(context, dynamic_model=True)
        assert_that(context.completed.returncode, equal_to(0), context.completed.stdout + context.completed.stderr)
        calls = {request["messages"][0]["content"]: request for request in context.model_requests}
        for operation in ["retain", "reflect", "consolidation", "startup", "held-before", "held-after"]:
            assert_that(calls[operation]["model"], equal_to("openrouter/contract/first"))
        for operation in ["updated-model", "updated-tools"]:
            assert_that(calls[operation]["model"], equal_to("openrouter/contract/second"))
        assert_that(calls["updated-model"]["user"], equal_to("org-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
        assert_that(calls["updated-tools"]["user"], equal_to("org-11111111-2222-3333-4444-555555555555"))
