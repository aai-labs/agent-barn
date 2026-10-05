from unittest.mock import MagicMock, patch

import pytest

from api.core.config import get_config
from api.domains.agents.service import (
    AgentService,
    filter_models_by_allowlist,
    is_model_allowed,
)
from api.infrastructure.openrouter.client import (
    CreditsStatus,
    OpenRouterClient,
    OpenRouterCredits,
    clear_models_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_models_cache()
    yield
    clear_models_cache()


def _mock_get(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    mock = MagicMock(return_value=resp)
    return mock


def _client() -> OpenRouterClient:
    return OpenRouterClient(config=get_config())


def test_list_models_maps_fields_and_skips_idless_entries():
    payload = {
        "data": [
            {
                "id": "qwen/qwen3.6-plus",
                "name": "Qwen3.6 Plus",
                "context_length": 32000,
                "pricing": {"prompt": "0.1"},
            },
            {"name": "no id here"},
        ]
    }
    with patch("api.infrastructure.openrouter.client.httpx.get", _mock_get(payload)):
        models = _client().list_models()

    assert models == [
        {
            "id": "qwen/qwen3.6-plus",
            "name": "Qwen3.6 Plus",
            "context_length": 32000,
            "pricing": {"prompt": "0.1"},
        }
    ]


def test_list_models_caches_across_calls():
    payload = {"data": [{"id": "qwen/qwen3.6-plus", "name": "Qwen"}]}
    mock = _mock_get(payload)
    with patch("api.infrastructure.openrouter.client.httpx.get", mock):
        client = _client()
        client.list_models()
        client.list_models()

    assert mock.call_count == 1


def test_list_models_falls_back_to_id_when_name_missing():
    payload = {"data": [{"id": "qwen/qwen3.6-plus"}]}
    with patch("api.infrastructure.openrouter.client.httpx.get", _mock_get(payload)):
        models = _client().list_models()

    assert models[0]["name"] == "qwen/qwen3.6-plus"


_CATALOG = [
    {"id": "qwen/qwen3.6-plus"},
    {"id": "openai/gpt-5-mini"},
    {"id": "openai/gpt-5"},
    {"id": "anthropic/claude-opus"},
]


def test_allowlist_empty_blocks_everything():
    assert filter_models_by_allowlist(_CATALOG, []) == []


def test_allowlist_glob_vendor_prefix():
    result = filter_models_by_allowlist(_CATALOG, ["openai/*"])
    assert [m["id"] for m in result] == ["openai/gpt-5-mini", "openai/gpt-5"]


def test_allowlist_multiple_patterns_and_exact():
    result = filter_models_by_allowlist(_CATALOG, ["qwen/qwen3.6-plus", "anthropic/*"])
    assert [m["id"] for m in result] == [
        "qwen/qwen3.6-plus",
        "anthropic/claude-opus",
    ]


def test_allowlist_is_case_insensitive():
    result = filter_models_by_allowlist(_CATALOG, ["OPENAI/GPT-5*"])
    assert [m["id"] for m in result] == ["openai/gpt-5-mini", "openai/gpt-5"]


def test_is_model_allowed_strips_gateway_prefix_and_matches_glob():
    assert is_model_allowed("litellm/openrouter/openai/gpt-5-mini", ["openai/*"])
    assert not is_model_allowed("litellm/openrouter/anthropic/claude", ["openai/*"])


def test_is_model_allowed_empty_allowlist_blocks_everything():
    assert not is_model_allowed("litellm/openrouter/anything/at-all", [])


def test_is_model_allowed_handles_unprefixed_value():
    assert is_model_allowed("openai/gpt-5-mini", ["openai/*"])
    assert not is_model_allowed("openai/gpt-5-mini", ["qwen/*"])


def _service(openrouter, allowlist=None, default_model=""):
    if allowlist is None:
        allowlist = [
            "qwen/*",
            "openai/*",
            "anthropic/*",
        ]  # pass everything in tests unless blocked
    config = MagicMock()
    config.agent_default_model = default_model

    org_lookup = MagicMock()
    org_lookup.get_allowed_models.return_value = allowlist

    # The picker's default now comes from the Organization's Agent Settings, which
    # fall back to AGENT_DEFAULT_MODEL. These tests are about how the resolved
    # default is surfaced, so they stub the resolution and keep their assertions.
    agent_settings_lookup = MagicMock()
    agent_settings_lookup.resolve_default_model.return_value = default_model

    return AgentService(
        repository=MagicMock(),
        connection_repository=MagicMock(),
        plugins=MagicMock(),
        override_repository=MagicMock(),
        authorization=MagicMock(),
        template_repository=MagicMock(),
        skill_repository=MagicMock(),
        k8s=MagicMock(),
        litellm=MagicMock(),
        openrouter=openrouter,
        config=config,
        shared_credential_repository=MagicMock(),
        event_delivery_dispatcher=MagicMock(),
        organization_lookup=org_lookup,
        agent_settings_lookup=agent_settings_lookup,
        agent_budgets=MagicMock(),
        restore_points=MagicMock(),
        selection=MagicMock(),
    )


def test_service_maps_catalog_to_litellm_openrouter_picker_options():
    openrouter = MagicMock()
    openrouter.list_models.return_value = [
        {
            "id": "qwen/qwen3.6-plus",
            "name": "Qwen3.6 Plus",
            "context_length": 32000,
            "pricing": {"prompt": "0.1"},
        }
    ]
    service = _service(openrouter, allowlist=["qwen/*"])
    service._org_id = MagicMock()

    options = service.list_models(MagicMock())

    assert options == [
        {
            "value": "litellm/openrouter/qwen/qwen3.6-plus",
            "label": "Qwen3.6 Plus",
            "contextLength": 32000,
            "pricing": {"prompt": "0.1"},
            "isDefault": False,
        }
    ]


def test_service_flags_and_surfaces_configured_default_first():
    openrouter = MagicMock()
    openrouter.list_models.return_value = [
        {"id": "qwen/qwen3.6-plus", "name": "Qwen"},
        {"id": "openai/gpt-5-mini", "name": "GPT-5 mini"},
    ]
    service = _service(
        openrouter,
        allowlist=["qwen/*", "openai/*"],
        default_model="litellm/openrouter/openai/gpt-5-mini",
    )
    service._org_id = MagicMock()

    options = service.list_models(MagicMock())

    assert options[0]["value"] == "litellm/openrouter/openai/gpt-5-mini"
    assert options[0]["isDefault"] is True
    assert [o["isDefault"] for o in options] == [True, False]


def test_service_injects_default_when_absent_from_catalog():
    openrouter = MagicMock()
    openrouter.list_models.return_value = [{"id": "qwen/qwen3.6-plus", "name": "Qwen"}]
    service = _service(
        openrouter,
        allowlist=["qwen/*"],
        default_model="litellm/openrouter/openai/gpt-5-mini",
    )
    service._org_id = MagicMock()

    options = service.list_models(MagicMock())

    assert options[0] == {
        "value": "litellm/openrouter/openai/gpt-5-mini",
        "label": "openai/gpt-5-mini",
        "contextLength": None,
        "pricing": None,
        "isDefault": True,
    }
    assert {o["value"] for o in options} == {
        "litellm/openrouter/openai/gpt-5-mini",
        "litellm/openrouter/qwen/qwen3.6-plus",
    }


def _credits(payload: dict, key: str = "sk-test") -> OpenRouterCredits:
    with (
        patch.object(get_config(), "openrouter_api_key", key),
        patch("api.infrastructure.openrouter.client.httpx.get", _mock_get(payload)),
    ):
        return _client().get_credits()


def test_credits_report_the_limit_and_what_is_left():
    credits = _credits({"data": {"limit": 500, "limit_remaining": 32.85}})

    assert credits.status is CreditsStatus.OK
    assert credits.remaining == 32.85
    assert credits.limit == 500.0


def test_an_explicit_null_remaining_means_the_key_has_no_limit():
    credits = _credits({"data": {"limit": None, "limit_remaining": None}})

    assert credits.status is CreditsStatus.NO_LIMIT
    assert credits.remaining is None


def test_an_absent_remaining_is_unavailable_not_no_limit():
    """A missing field is not OpenRouter saying "no limit" — it is no answer.

    Treating them alike caches a healthy-looking state from a malformed response
    and silences the warning that says the balance is unknown.
    """
    credits = _credits({"data": {}})

    assert credits.status is CreditsStatus.UNAVAILABLE


def test_a_non_numeric_remaining_is_unavailable():
    credits = _credits({"data": {"limit_remaining": "lots"}})

    assert credits.status is CreditsStatus.UNAVAILABLE


def test_a_payload_that_is_not_an_object_is_unavailable():
    credits = _credits({"data": []})

    assert credits.status is CreditsStatus.UNAVAILABLE


def test_an_unusable_limit_still_leaves_the_remaining_balance_usable():
    """The limit only enriches the display; losing it must not lose the balance."""
    credits = _credits({"data": {"limit": "unlimited", "limit_remaining": 12.5}})

    assert credits.status is CreditsStatus.OK
    assert credits.remaining == 12.5
    assert credits.limit is None


def test_without_a_key_the_balance_is_unavailable_and_nothing_is_polled():
    credits = _credits({"data": {"limit_remaining": 5.0}}, key="")

    assert credits.status is CreditsStatus.UNAVAILABLE
