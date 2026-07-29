import json

from hamcrest import assert_that, equal_to, is_, none

from api.domains.agents.error_messages import (
    build_clean_error_body,
    classify_terminal_llm_error,
)


class TestClassifyTerminalLlmError:
    def test_401_returns_auth_message(self):
        result = classify_terminal_llm_error(401)
        assert_that(
            result,
            equal_to("LLM API key is invalid or expired. Check your API key configuration."),
        )

    def test_402_returns_credits_message(self):
        result = classify_terminal_llm_error(402)
        assert_that(
            result,
            equal_to("OpenRouter credits exhausted. Add credits at https://openrouter.ai/credits."),
        )

    def test_403_returns_access_denied_message(self):
        result = classify_terminal_llm_error(403)
        assert_that(
            result,
            equal_to("LLM API access denied. Check your account permissions."),
        )

    def test_200_returns_none(self):
        assert_that(classify_terminal_llm_error(200), is_(none()))

    def test_429_returns_none(self):
        assert_that(classify_terminal_llm_error(429), is_(none()))

    def test_500_returns_none(self):
        assert_that(classify_terminal_llm_error(500), is_(none()))


class TestBuildCleanErrorBody:
    def test_produces_openai_format_json(self):
        body = build_clean_error_body(402, "Credits exhausted.")
        parsed = json.loads(body)
        assert_that(parsed["error"]["message"], equal_to("Credits exhausted."))
        assert_that(parsed["error"]["code"], equal_to("402"))
        assert_that(parsed["error"]["type"], is_(none()))
        assert_that(parsed["error"]["param"], is_(none()))

    def test_status_code_is_stringified(self):
        body = build_clean_error_body(401, "Bad key.")
        parsed = json.loads(body)
        assert_that(parsed["error"]["code"], equal_to("401"))
