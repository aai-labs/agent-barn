"""A Playbook Extraction run end to end in the worker, against a loopback LiteLLM proxy.

The run reads the source Agent's conversations and long-term memories, asks the model
for notes per conversation and then for the playbook, and writes an Organization Skill
Draft. Every model call is billed to the source Agent's own key.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock
from uuid import uuid7

import pytest
from fastapi import HTTPException
from hamcrest import (
    assert_that,
    contains_exactly,
    contains_string,
    equal_to,
    has_entries,
    has_length,
    has_properties,
    is_not,
    none,
    not_none,
    only_contains,
    starts_with,
)
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agent_memory.gateway_models import MemoryViewItem, MemoryViewPage
from api.domains.agent_memory.view_client import MemoryViewClient
from api.domains.conversations.models import MessageDirection
from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionStatus
from api.domains.playbooks.platform_repository import PlatformPlaybookRepository
from api.domains.playbooks.prompts import NOTES_SYSTEM_PROMPT, PLAYBOOK_SYSTEM_PROMPT
from api.domains.skills.models import Skill
from api.domains.skills.repository import SkillRepository
from api.domains.skills.service import PlaybookTargetUnavailable, SkillService
from api.tests.core.givenpy import LambdaWith, given, then, when
from api.tests.helpers.litellm_proxy import StubProxy, StubReply, completion, litellm_proxy
from api.tests.steps.agent import FAKE_LITELLM_KEY, there_is_a_skill, there_is_an_agent
from api.tests.steps.playbooks import (
    playbooks_api_setup,
    process_extraction,
    the_skill_has_a_draft,
    there_is_a_conversation,
    there_is_a_playbook_extraction,
)

IN = MessageDirection.INBOUND
OUT = MessageDirection.OUTBOUND

PLAYBOOK_BODY = "# Refunds\n\n## How we work\n\n1. Check the order first (seen in 2 conversations)."
PLAYBOOK = {
    "description": "Use when preparing refunds for customers.",
    "conventions": [
        {"rule": "Use Vilnius time for dates and deadlines.", "conversations": 2},
        {"rule": "Ask before changing any record.", "conversations": 1},
    ],
    "body": PLAYBOOK_BODY,
}


def _notes(task: str, reusable: bool = True) -> dict[str, Any]:
    return {
        "task": task,
        "reusable": reusable,
        "steps": ["Look up the order"],
        "tools": ["aai-cli orders"],
        "corrections": ["Refund half, not all"],
        "preferences": [],
        "outcome": "Done",
    }


def _system(request: dict[str, Any]) -> str:
    return request["json"]["messages"][0]["content"]


def _user(request: dict[str, Any]) -> str:
    return request["json"]["messages"][1]["content"]


def model_replies(
    notes: Any = None,
    playbook: Any = PLAYBOOK,
    notes_status: int = 200,
    playbook_status: int = 200,
    playbook_finish_reason: str = "stop",
) -> StubProxy:
    """Notes for each conversation, then the playbook; each reply reports usage and cost."""

    def respond(posted: dict[str, Any]) -> StubReply:
        system = posted["messages"][0]["content"]
        if system == NOTES_SYSTEM_PROMPT:
            body = notes(posted) if callable(notes) else (notes or _notes("Refund an order"))
            if notes_status != 200:
                return notes_status, body, {}
            return notes_status, completion(json.dumps(body), 1_000, 100), {"x-litellm-response-cost": "0.001"}
        content = playbook if isinstance(playbook, str) else json.dumps(playbook)
        return (
            playbook_status,
            completion(content, 3_000, 800, finish_reason=playbook_finish_reason),
            {"x-litellm-response-cost": "0.01"},
        )

    return StubProxy(respond=respond)


def the_model_proxy_is(stub: StubProxy):
    def step(context):
        context.proxy = stub
        manager = litellm_proxy(stub)
        url = manager.__enter__()
        config = context.injector.get(Config)
        previous = config.litellm_base_url
        config.litellm_base_url = url

        def stop():
            config.litellm_base_url = previous
            manager.__exit__(None, None, None)

        return LambdaWith(lambda: None, stop)

    return step


def long_term_memories(*texts: str):
    def step(context):
        page = MemoryViewPage(
            items=[
                MemoryViewItem(id=str(uuid7()), type="world", text=t, mentioned_at=None, shared=False) for t in texts
            ],
            total=len(texts),
        )
        context.injector.get(MemoryViewClient).list_memories = Mock(return_value=page)

    return step


def long_term_memory_is_unavailable():
    def step(context):
        context.injector.get(MemoryViewClient).list_memories = Mock(side_effect=HTTPException(503, "unavailable"))

    return step


def the_platform_model_is(model: str):
    def step(context):
        context.injector.get(PlatformPlaybookRepository).set_model(
            model, "openrouter/openai/gpt-4.1-mini", context.user.id, "Platform Admin"
        )

    return step


def two_refund_conversations():
    def step(context):
        start = datetime.now(UTC) - timedelta(days=1)
        there_is_a_conversation(
            "thread-1",
            start,
            [(0, IN, "Refund order 42"), (20, IN, "No, only half of it"), (90, OUT, "Refunded half.")],
            tool_session_id="run-1",
            tool_calls=((30, "exec", {"command": "aai-cli orders show 42"}, "order 42"),),
        )(context)
        there_is_a_conversation(
            "thread-2", start + timedelta(hours=2), [(0, IN, "Refund order 7"), (60, OUT, "Refunded.")]
        )(context)

    return step


def _setup(*steps):
    return playbooks_api_setup(
        there_is_an_agent(name="Billing"), long_term_memories("Refunds over 500 EUR need approval"), *steps
    )


def _skill(context, extraction: PlaybookExtraction) -> Skill:
    skill = context.injector.get(SkillRepository).get_by_id(extraction.skill_id)
    assert skill is not None
    return skill


def _draft_files(context, skill_id) -> dict[str, str]:
    repository = context.injector.get(SkillRepository)
    draft = repository.get_draft(skill_id)
    assert draft is not None
    return {f.path: f.content for f in repository.get_draft_files(draft.id)}


def test_a_run_writes_its_playbook_as_a_new_organization_skill_draft():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        with when("the worker runs the extraction"):
            run = process_extraction(context)

        with then("the run succeeds and names the new Skill"):
            assert_that(run.status, equal_to(PlaybookExtractionStatus.SUCCEEDED))
            skill = _skill(context, run)
            assert_that(
                (skill.name, skill.organization_id, skill.agent_id),
                equal_to(("Billing playbook", context.organization.id, None)),
            )

        with then("the Skill has an unpublished draft holding the playbook with Skill frontmatter"):
            files = _draft_files(context, skill.id)
            assert_that(list(files), contains_exactly("SKILL.md"))
            assert_that(
                files["SKILL.md"],
                equal_to(
                    f'---\nname: {skill.slug}\ndescription: "Use when preparing refunds for customers."\n---\n\n'
                    + PLAYBOOK_BODY
                    + "\n"
                ),
            )
            assert_that(context.injector.get(SkillRepository).get_latest_version(skill.id), none())
            assert_that(run.result_markdown, equal_to(files["SKILL.md"]))


def test_organization_conventions_are_kept_on_the_run_apart_from_the_playbook():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        with when("the worker runs the extraction"):
            run = process_extraction(context)

        with then("the proposed conventions are stored for review and left out of the Skill"):
            assert_that(
                run.result_conventions,
                equal_to(
                    [
                        {"rule": "Use Vilnius time for dates and deadlines.", "conversations": 2},
                        {"rule": "Ask before changing any record.", "conversations": 1},
                    ]
                ),
            )
            assert_that(_draft_files(context, run.skill_id)["SKILL.md"], is_not(contains_string("Vilnius")))


def test_malformed_conventions_are_dropped_without_failing_the_run():
    malformed = {**PLAYBOOK, "conventions": [{"rule": ""}, "not an object", {"rule": "Answer in English."}]}
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(playbook=malformed)),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the model answers with some malformed conventions"):
            run = process_extraction(context)

        with then("the run succeeds with only the well-formed one"):
            assert_that(run.status, equal_to(PlaybookExtractionStatus.SUCCEEDED))
            assert_that(run.result_conventions, equal_to([{"rule": "Answer in English.", "conversations": 1}]))


def test_a_run_records_what_it_read_and_what_it_cost():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        with when("the worker runs the extraction"):
            run = process_extraction(context)

        with then("inputs, model, prompt version, tokens, and cost are on the run"):
            assert_that(
                run,
                has_properties(
                    session_count=2,
                    message_count=5,
                    tool_call_count=1,
                    memory_count=1,
                    prompt_tokens=5_000,
                    completion_tokens=1_000,
                    cost_usd=Decimal("0.012"),
                    model="openrouter/openai/gpt-4.1-mini",
                ),
            )
            assert_that(run.session_keys, contains_exactly("thread-2", "thread-1"))
            assert_that(run.prompt_version or "", starts_with("playbook-"))
            assert_that(run.finished_at, not_none())


def test_every_model_call_uses_the_source_agents_key_and_the_platform_model():
    with given(
        _setup(
            two_refund_conversations(),
            the_platform_model_is("openrouter/anthropic/claude-sonnet"),
            the_model_proxy_is(model_replies()),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the worker runs the extraction"):
            process_extraction(context)

        with then("three calls were billed to the Agent's key with the chosen model"):
            requests = context.proxy.requests
            assert_that(requests, has_length(3))
            assert_that([r["authorization"] for r in requests], only_contains(equal_to(f"Bearer {FAKE_LITELLM_KEY}")))
            assert_that(
                [r["json"]["model"] for r in requests], only_contains(equal_to("openrouter/anthropic/claude-sonnet"))
            )


def test_each_conversation_is_read_once_and_memories_reach_the_playbook_step():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        with when("the worker runs the extraction"):
            process_extraction(context)

        with then("each transcript went to its own notes call, with the paired Tool Call"):
            notes_inputs = [_user(r) for r in context.proxy.requests if _system(r) == NOTES_SYSTEM_PROMPT]
            assert_that(notes_inputs, has_length(2))
            thread_one = next(text for text in notes_inputs if "Refund order 42" in text)
            assert_that(thread_one, contains_string("Person (Ana): No, only half of it"))
            assert_that(thread_one, contains_string("aai-cli orders show 42"))

        with then("the playbook call received the notes and the long-term memory"):
            [final] = [r for r in context.proxy.requests if _system(r) == PLAYBOOK_SYSTEM_PROMPT]
            assert_that(_user(final), contains_string("Notes from 2 conversations"))
            assert_that(_user(final), contains_string("Refund half, not all"))
            assert_that(_user(final), contains_string("- Refunds over 500 EUR need approval"))


def test_conversations_with_nothing_to_teach_are_left_out_of_the_playbook_step():
    def notes(posted):
        transcript = posted["messages"][1]["content"]
        return _notes("Say hello", reusable=False) if "Refund order 7" in transcript else _notes("Refund an order")

    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(notes=notes)),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the worker runs the extraction"):
            process_extraction(context)

        with then("only the reusable conversation's notes reach the playbook step"):
            [final] = [r for r in context.proxy.requests if _system(r) == PLAYBOOK_SYSTEM_PROMPT]
            assert_that(_user(final), contains_string("Notes from 1 conversations"))
            assert_that(_user(final), is_not(contains_string("Say hello")))


def test_a_run_continues_without_long_term_memory_when_it_is_unavailable():
    with given(
        playbooks_api_setup(
            there_is_an_agent(),
            long_term_memory_is_unavailable(),
            two_refund_conversations(),
            the_model_proxy_is(model_replies()),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the worker runs the extraction"):
            run = process_extraction(context)

        with then("it still succeeds, recording that no memories were read"):
            assert_that((run.status, run.memory_count), equal_to((PlaybookExtractionStatus.SUCCEEDED, 0)))


def test_refreshing_a_playbook_writes_the_next_draft_of_the_same_skill():
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies()),
            there_is_a_skill(name="Refunds playbook"),
        )
    ) as context:
        there_is_a_playbook_extraction(skill_name="Refunds playbook", skill_id=context.skill.id)(context)
        with when("the worker refreshes the existing playbook"):
            run = process_extraction(context)

        with then("the existing Skill gains a draft and keeps its published version"):
            assert_that(run.skill_id, equal_to(context.skill.id))
            assert_that(_draft_files(context, context.skill.id)["SKILL.md"], contains_string(PLAYBOOK_BODY))
            assert_that(context.injector.get(SkillRepository).get_latest_version(context.skill.id).version, equal_to(1))


def test_a_draft_started_after_the_request_is_never_overwritten():
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies()),
            there_is_a_skill(name="Refunds playbook"),
        )
    ) as context:
        there_is_a_playbook_extraction(skill_name="Refunds playbook", skill_id=context.skill.id)(context)
        the_skill_has_a_draft()(context)
        with when("the worker finishes a run whose target gained a draft meanwhile"):
            run = process_extraction(context)

        with then("the run fails, the person's draft is intact, and the paid-for playbook is kept on the run"):
            assert_that(run.status, equal_to(PlaybookExtractionStatus.FAILED))
            assert_that(run.error_code, equal_to("draft_conflict"))
            assert_that(_draft_files(context, context.skill.id)["SKILL.md"], equal_to("# Unpublished edits"))
            assert_that(run.result_markdown or "", contains_string(PLAYBOOK_BODY))
            assert_that(run.prompt_tokens, equal_to(5_000))


def test_a_new_playbook_whose_name_was_taken_meanwhile_gets_a_suffix():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        there_is_a_skill(name="Billing playbook")(context)
        with when("the worker creates the new playbook"):
            run = process_extraction(context)

        with then("it is named with a suffix rather than failing"):
            assert_that(_skill(context, run).name, equal_to("Billing playbook (2)"))


def test_a_run_with_no_conversations_in_its_window_calls_no_model():
    with given(_setup(the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())) as context:
        with when("the worker runs an extraction for an Agent with no recent conversations"):
            run = process_extraction(context)

        with then("it fails without spending anything"):
            assert_that((run.status, run.error_code), equal_to((PlaybookExtractionStatus.FAILED, "no_sessions")))
            assert_that(context.proxy.requests, has_length(0))


def test_an_exhausted_budget_fails_the_run():
    budget = {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded"}}
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(notes=lambda _: budget, notes_status=400)),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("LiteLLM refuses the Agent's key for budget"):
            run = process_extraction(context)

        with then("the run fails as over its spend limit and writes no Skill"):
            assert_that(run.error_code, equal_to("spend_limit_reached"))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(Skill)).all(), has_length(0))


def test_a_playbook_answer_in_the_wrong_shape_fails_the_run():
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(playbook="not json")),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the model answers the playbook step with plain text"):
            run = process_extraction(context)

        with then("the run fails with a model error and keeps the spent tokens"):
            assert_that((run.error_code, run.prompt_tokens), equal_to(("model_error", 5_000)))


def test_a_playbook_answer_cut_off_at_the_token_limit_fails_the_run_as_truncated():
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(playbook='{"description": "Use when', playbook_finish_reason="length")),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the model stops at the playbook step's token limit"):
            run = process_extraction(context)

        with then("the run says the answer was cut off, writes no Skill, and keeps the spent tokens"):
            assert_that((run.error_code, run.prompt_tokens), equal_to(("answer_truncated", 5_000)))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(Skill)).all(), has_length(0))


def test_a_playbook_wrapped_in_a_code_fence_is_still_read():
    fenced = "```json\n" + json.dumps(PLAYBOOK) + "\n```"
    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(playbook=fenced)),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("the model wraps its JSON answer in a Markdown code fence"):
            run = process_extraction(context)

        with then("the playbook is written as usual"):
            assert_that(run.status, equal_to(PlaybookExtractionStatus.SUCCEEDED))
            assert_that(run.result_markdown or "", contains_string(PLAYBOOK_BODY))


def test_cancelling_while_notes_are_taken_stops_the_run_before_the_playbook_step():
    def notes(posted):
        with Session(context.postgres_delegate.engine) as session:
            run = session.get(PlaybookExtraction, context.extraction.id)
            assert run is not None
            run.status = PlaybookExtractionStatus.CANCELLED
            session.add(run)
            session.commit()
        return _notes("Refund an order")

    with given(
        _setup(
            two_refund_conversations(),
            the_model_proxy_is(model_replies(notes=notes)),
            there_is_a_playbook_extraction(),
        )
    ) as context:
        with when("a person cancels while the first notes are being taken"):
            run = process_extraction(context)

        with then("the run stays cancelled, no playbook is requested, and no Skill is written"):
            assert_that(run.status, equal_to(PlaybookExtractionStatus.CANCELLED))
            assert_that([_system(r) for r in context.proxy.requests], only_contains(equal_to(NOTES_SYSTEM_PROMPT)))
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(Skill)).all(), has_length(0))


def test_a_failed_run_records_the_notes_calls_still_in_flight_when_one_failed():
    budget = {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded"}}

    def respond(posted: dict[str, Any]) -> StubReply:
        if "Refund order 7" in posted["messages"][1]["content"]:
            return 400, budget, {}
        # Still running when the other call fails, and billed when it finishes.
        time.sleep(0.5)
        return 200, completion(json.dumps(_notes("Refund an order")), 1_000, 100), {"x-litellm-response-cost": "0.001"}

    with given(
        _setup(
            two_refund_conversations(), the_model_proxy_is(StubProxy(respond=respond)), there_is_a_playbook_extraction()
        )
    ) as context:
        with when("one notes call is refused while another is still running"):
            run = process_extraction(context)

        with then("the run fails with the tokens and cost of the call that finished afterwards"):
            assert_that(run.error_code, equal_to("spend_limit_reached"))
            assert_that((run.prompt_tokens, run.completion_tokens), equal_to((1_000, 100)))
            assert_that(run.cost_usd, equal_to(Decimal("0.001")))


def test_a_new_playbook_that_cannot_be_written_leaves_no_skill_behind():
    with given(_setup()) as context:
        skills = context.injector.get(SkillService)
        with when("the rendered SKILL.md is refused by file validation"):
            with pytest.raises(PlaybookTargetUnavailable):
                skills.write_playbook_draft(
                    context.organization.id, None, "Billing playbook", "Use when billing.", lambda slug: "x" * 2_000_000
                )

        with then("no Skill holds the name, so a retry can use it"):
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(Skill)).all(), has_length(0))


def test_run_lists_say_whether_the_playbook_still_has_an_unpublished_draft():
    with given(
        _setup(two_refund_conversations(), the_model_proxy_is(model_replies()), there_is_a_playbook_extraction())
    ) as context:
        run = process_extraction(context)
        with when("the Owner lists the Organization's runs after the draft was written"):
            response = context.client.get(
                "/api/v1/organizations/{organization_id}/playbook-extractions",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )

        with then("the run says its Skill has a draft, so it cannot take the next one yet"):
            [item] = response.json()["items"]
            assert_that(item, has_entries(skill_id=str(run.skill_id), skill_has_draft=True))
