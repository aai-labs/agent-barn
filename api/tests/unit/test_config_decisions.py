"""The deployment's decision models (AF-449): a name for each slug, and a default among them."""

from typing import Any

import pytest
from hamcrest import assert_that, equal_to
from pydantic import ValidationError

from api.core.config import Config


def _config(models: dict[str, str] | None = None, default: str | None = None) -> Config:
    decisions: dict[str, Any] = {}
    if models is not None:
        decisions["decision_models"] = models
    if default is not None:
        decisions["decision_default_model"] = default
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        organization_default_llm_budget_usd=100,
        agent_default_llm_budget_usd=25,
        **decisions,
    )


def test_jev_answers_by_default():
    config = _config()

    assert_that(config.decision_models[config.decision_default_model], equal_to("openrouter/typesafe/jev-1.14"))


def test_a_deployment_can_name_its_own_models():
    config = _config({"jev": "openrouter/typesafe/jev-1.15"}, "jev")

    assert_that(config.decision_models, equal_to({"jev": "openrouter/typesafe/jev-1.15"}))


def test_a_default_that_is_not_configured_refuses_to_boot():
    with pytest.raises(ValidationError, match="DECISION_DEFAULT_MODEL"):
        _config({"jev": "openrouter/typesafe/jev-1.14"}, "openai")
