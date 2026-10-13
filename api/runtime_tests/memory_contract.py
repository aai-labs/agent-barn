"""Shared observable contracts for both memory-enabled runtime images."""

import json
from pathlib import Path

from hamcrest import assert_that, contains_string, equal_to, has_item, is_, not_

from api.runtime_tests.memory_helpers import (
    NATIVE_FACT,
    NATIVE_USER,
    RECALLED_FACT,
    RUNTIME_KEY,
    configure_memory,
    memory_http_boundary_is_ready,
    memory_requests,
    runtime_is_present,
    runtime_memory_is_configured,
    stale_memory_settings_are_present,
    start_memory_runtime,
)
from api.tests.core.givenpy import given, then, when


def runtime_should_have_started(context):
    assert_that(context.completed.returncode, equal_to(0), context.completed.stdout + context.completed.stderr)
    assert_that(bool(context.result), is_(True), context.completed.stdout + context.completed.stderr)
    assert_that(context.result["native_prompt"], contains_string(NATIVE_FACT))
    assert_that(context.result["native_prompt"], contains_string(NATIVE_USER))
    assert_that(context.result["saved_credential"], is_(False))


def memory_should_start(
    runtime: str, image: str, root: Path, *, organization_write_status: int = 202, explicit_recall_status: int = 200
):
    with given(
        [
            runtime_is_present(runtime, image, root),
            memory_http_boundary_is_ready(
                health_denials=3,
                organization_write_status=organization_write_status,
                explicit_recall_status=explicit_recall_status,
            ),
            stale_memory_settings_are_present(),
            runtime_memory_is_configured(enabled=True),
        ]
    ) as context:
        with when("the opted-in runtime starts and completes a turn in a new session"):
            start_memory_runtime(context)
        with then("native memory and the Hindsight provider should both load"):
            runtime_should_have_started(context)
            assert_that(
                context.result["organization_tool_exit"],
                equal_to(0 if organization_write_status == 202 else 1),
                str(context.result),
            )
            if organization_write_status == 403:
                assert_that(
                    context.result["organization_tool_error"],
                    contains_string("Organization Memory write access is required"),
                )
            shared = [request for request in context.requests if request["path"] == "/memory/v1/organization-memory"]
            assert_that(len(shared), equal_to(1))
            assert_that(shared[0]["payload"], equal_to({"content": "Organization release convention."}))
            assert_that(shared[0]["authorization"], equal_to(f"Bearer {RUNTIME_KEY}"))
            provider = "hindsight" if runtime == "hermes" else "hindsight-openclaw"
            assert_that(context.result["providers"], has_item(provider))
            if runtime == "openclaw":
                assert_that(context.result["providers"], has_item("memory-core"))
                assert_that(context.result["plugin_errors"], equal_to([]))
        with then("the first prompt should contain recalled memory and the shared-save instructions"):
            if runtime == "hermes":
                prompts = [request["payload"] for request in context.requests if "/llm/" in request["path"]]
                assert_that(json.dumps(prompts), contains_string(RECALLED_FACT))
                turns = [payload for payload in prompts if isinstance(payload, dict) and "messages" in payload]
                system = "\n".join(
                    message["content"] for message in turns[0]["messages"] if message["role"] == "system"
                )
                assert_that(context.result["response"], equal_to("Memory contract response."))
            else:
                assert_that(context.result["recalled"], contains_string(RECALLED_FACT))
                system = context.result["system_prompt"]
            assert_that(system, contains_string("/usr/local/bin/agentbarn-memory remember-organization"))
            assert_that(system, contains_string("A successful private retain does not confirm"))
            assert_that(system, contains_string("/usr/local/bin/agentbarn-memory recall --thorough"))
            assert_that(system, contains_string("other Agents' private"))
        with then("explicit search distinguishes a miss from an outage and supports a focused retry"):
            searches = context.result["explicit_recalls"]
            if explicit_recall_status != 200:
                assert_that(searches, equal_to([{"exit_code": 1, "outcome": {"status": "unavailable"}}]))
            else:
                assert_that(
                    searches,
                    equal_to(
                        [
                            {"exit_code": 0, "outcome": {"status": "not_found", "memories": []}},
                            {"exit_code": 0, "outcome": {"status": "found", "memories": [RECALLED_FACT]}},
                        ]
                    ),
                )
                explicit = [
                    request["payload"]
                    for request in memory_requests(context)
                    if request["method"] == "POST"
                    and request["payload"].get("query") in {"Explicit release convention", "Focused release convention"}
                ]
                assert_that(
                    [(payload["budget"], payload["max_tokens"]) for payload in explicit],
                    equal_to([("mid", 4096), ("high", 8192)]),
                )
        with then("the real plugin should send the completed turn to the gateway with its current credential"):
            requests = memory_requests(context)
            assert_that(context.health_denials, equal_to(0))
            assert_that(
                [request["authorization"] for request in requests], not_(has_item("Bearer stale-runtime-contract-key"))
            )
            assert_that(all(request["authorization"] == f"Bearer {RUNTIME_KEY}" for request in requests), is_(True))
            posts = [request for request in requests if request["method"] == "POST"]
            assert_that([request["path"].rsplit("/", 1)[-1] for request in posts], has_item("recall"))
            retains = [request for request in posts if request["path"].endswith("/memories")]
            assert_that(len(retains), equal_to(1), str(requests))
            assert_that(json.dumps(retains[0]["payload"]), contains_string("Memory contract response."))
            assert_that(json.dumps(retains[0]["payload"]), contains_string("durable facts"))
            assert_that([request for request in requests if request["method"] == "PATCH"], equal_to([]))


def memory_should_stop(runtime: str, image: str, root: Path):
    with given(
        [
            runtime_is_present(runtime, image, root),
            memory_http_boundary_is_ready(),
            runtime_memory_is_configured(enabled=True),
        ]
    ) as context:
        with when("the Agent starts with memory enabled"):
            start_memory_runtime(context)
        with then("the enabled runtime should have loaded successfully"):
            runtime_should_have_started(context)
            assert_that(bool(memory_requests(context)), is_(True))
        with when("memory is disabled and the same persistent volume is restarted"):
            configure_memory(context, enabled=False)
            context.requests.clear()
            start_memory_runtime(context)
        with then("native memory should survive and stale Hindsight settings should be removed"):
            runtime_should_have_started(context)
            assert_that(context.result["saved_settings_exist"], is_(False))
            provider = "hindsight" if runtime == "hermes" else "hindsight-openclaw"
            assert_that(context.result["providers"], not_(has_item(provider)))
            if runtime == "openclaw":
                assert_that(context.result["providers"], has_item("memory-core"))
        with then("the runtime should send no more memory requests"):
            assert_that(memory_requests(context), equal_to([]))
            if runtime == "hermes":
                prompts = [request["payload"] for request in context.requests if "/llm/" in request["path"]]
                assert_that(json.dumps(prompts), not_(contains_string("remember-organization")))
            else:
                assert_that(context.result["system_prompt"], not_(contains_string("remember-organization")))
