from api.domains.agents.service import is_model_allowed, filter_models_by_allowlist

def test_is_model_allowed_empty_rejects_everything():
    assert is_model_allowed("litellm/openrouter/openai/gpt-4o", []) is False
    assert is_model_allowed("openai/gpt-4o", []) is False
    assert is_model_allowed("any", []) is False

def test_is_model_allowed_matches_glob():
    assert is_model_allowed("litellm/openrouter/openai/gpt-4o", ["openai/gpt-4*"]) is True
    assert is_model_allowed("litellm/openrouter/anthropic/claude-3", ["openai/*"]) is False
    assert is_model_allowed("litellm/openrouter/anthropic/claude-3", ["*"]) is True

def test_filter_models_by_allowlist_empty_rejects_everything():
    catalog = [
        {"id": "openai/gpt-4o", "name": "GPT-4o"},
        {"id": "anthropic/claude-3", "name": "Claude 3"},
    ]
    assert filter_models_by_allowlist(catalog, []) == []

def test_filter_models_by_allowlist_matches_glob():
    catalog = [
        {"id": "openai/gpt-4o", "name": "GPT-4o"},
        {"id": "anthropic/claude-3", "name": "Claude 3"},
    ]
    filtered = filter_models_by_allowlist(catalog, ["openai/*"])
    assert len(filtered) == 1
    assert filtered[0]["id"] == "openai/gpt-4o"
