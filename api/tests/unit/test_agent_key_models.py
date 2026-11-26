from hamcrest import assert_that, equal_to

from api.domains.agents.key_models import key_models

DECISION_MODEL = "openrouter/typesafe/jev-1.14"
PLAYBOOK_MODEL = "openrouter/openai/gpt-4.1-mini"


def test_agent_models_are_cut_as_the_runtimes_cut_them():
    assert_that(
        key_models(["litellm/openrouter/z-ai/glm-5.2", "gpt-5-mini"], []),
        equal_to(["gpt-5-mini", "openrouter/z-ai/glm-5.2"]),
    )


def test_platform_models_are_kept_as_they_are():
    assert_that(key_models([], [DECISION_MODEL, PLAYBOOK_MODEL]), equal_to([PLAYBOOK_MODEL, DECISION_MODEL]))


def test_empty_entries_are_dropped_and_the_rest_deduplicated_and_sorted():
    assert_that(
        key_models(
            ["", "litellm/", "litellm/openrouter/z-ai/glm-5.2", "litellm/openrouter/z-ai/glm-5.2"],
            [DECISION_MODEL, "", "openrouter/z-ai/glm-5.2"],
        ),
        equal_to([DECISION_MODEL, "openrouter/z-ai/glm-5.2"]),
    )
