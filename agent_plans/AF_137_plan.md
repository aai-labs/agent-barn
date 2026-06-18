# Plan: Automate Slack Bot Creation (AF-137)

## Context

Creating a Slack agent currently requires 5+ manual steps at api.slack.com (create app from manifest, install it, generate tokens). This change automates app creation via Slack's `apps.manifest.create` API using a personal **configuration token** stored per-user. After creation, users still get bot/app tokens manually but with **direct links** to the specific app's pages — reducing steps from ~8 to ~3.

**Non-negotiable:** The "I already have a Slack app" path, Teams creation, conversations, tool calls, and all other existing features must remain unchanged.

**Methodology:** TDD — tests are written before implementation where applicable. Each step is independently testable and isolated. Steps are ordered so dependencies are satisfied.

---

## Step 1: Manifest Builder — Tests then Implementation

A pure function with zero dependencies. Easiest to TDD.

### 1a. TEST: `api/tests/unit/test_slack_manifest.py`

```python
from api.infrastructure.slack.manifest import build_slack_app_manifest


def test_build_manifest_contains_expanded_scopes():
    manifest = build_slack_app_manifest("TestBot", "A test bot")
    scopes = manifest["oauth_config"]["scopes"]["bot"]
    for scope in ["files:write", "canvases:read", "pins:write", "reactions:read", "search:read.users"]:
        assert scope in scopes


def test_build_manifest_contains_expanded_events():
    manifest = build_slack_app_manifest("TestBot", "A test bot")
    events = manifest["settings"]["event_subscriptions"]["bot_events"]
    for event in ["channel_rename", "pin_added", "reaction_added", "member_joined_channel"]:
        assert event in events


def test_build_manifest_socket_mode_enabled():
    manifest = build_slack_app_manifest("TestBot", "A test bot")
    assert manifest["settings"]["socket_mode_enabled"] is True
```

**Verify:** `cd api && uv run python -m pytest tests/unit/test_slack_manifest.py -v` — all 3 tests should FAIL (module not found).

### 1b. IMPLEMENT: `api/infrastructure/slack/manifest.py`

```python
"""Slack app manifest builder for automated app creation."""

BOT_SCOPES: list[str] = [
    "app_mentions:read",
    "canvases:read",
    "canvases:write",
    "channels:history",
    "channels:join",
    "channels:read",
    "chat:write",
    "chat:write.customize",
    "chat:write.public",
    "emoji:read",
    "files:read",
    "files:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "im:write",
    "mpim:history",
    "mpim:read",
    "mpim:write",
    "pins:read",
    "pins:write",
    "reactions:read",
    "reactions:write",
    "search:read.users",
    "users:read",
    "users:read.email",
]

BOT_EVENTS: list[str] = [
    "app_mention",
    "channel_rename",
    "member_joined_channel",
    "member_left_channel",
    "message.channels",
    "message.groups",
    "message.im",
    "message.mpim",
    "pin_added",
    "pin_removed",
    "reaction_added",
    "reaction_removed",
]


def build_slack_app_manifest(
    name: str,
    description: str,
    background_color: str = "#4A154B",
) -> dict:
    return {
        "display_information": {
            "name": name,
            "description": description,
            "background_color": background_color,
        },
        "features": {
            "app_home": {
                "home_tab_enabled": False,
                "messages_tab_enabled": True,
                "messages_tab_read_only_enabled": False,
            },
            "bot_user": {
                "display_name": name,
                "always_online": True,
            },
        },
        "oauth_config": {
            "scopes": {"bot": list(BOT_SCOPES)},
        },
        "settings": {
            "event_subscriptions": {"bot_events": list(BOT_EVENTS)},
            "interactivity": {"is_enabled": True},
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }
```

**Verify:** Re-run `cd api && uv run python -m pytest tests/unit/test_slack_manifest.py -v` — all 3 tests PASS.

---

## Step 2: Config Token Infrastructure — Tests then Implementation

Pure functions that call Slack APIs via the existing `request_json` transport. All Slack calls are mocked in tests.

### 2a. TEST: `api/tests/unit/test_slack_config_token.py`

```python
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.infrastructure.slack.config_token import (
    create_slack_app,
    rotate_refresh_token,
    validate_config_access_token,
    validate_config_credential,
)

_TRANSPORT = "api.infrastructure.slack.config_token.request_json"


@pytest.mark.parametrize("token,expected_fragment", [
    ("xoxb-fake", "bot token"),
    ("xapp-fake", "app-level token"),
    ("xoxp-fake", "user token"),
])
def test_validate_config_access_token_rejects_wrong_types(token, expected_fragment):
    with pytest.raises(HTTPException) as exc:
        validate_config_access_token(token)
    assert exc.value.status_code == 400
    assert expected_fragment in exc.value.detail


@patch(_TRANSPORT, return_value={"ok": True})
def test_validate_config_access_token_success(mock_rj):
    validate_config_access_token("valid-config-token")
    mock_rj.assert_called_once()


@patch(_TRANSPORT, return_value={"ok": False, "error": "invalid_auth"})
def test_validate_config_access_token_failure(mock_rj):
    with pytest.raises(HTTPException) as exc:
        validate_config_access_token("bad-token")
    assert exc.value.status_code == 400
    assert "invalid_auth" in exc.value.detail


@patch(_TRANSPORT, return_value={"ok": True, "token": "xoxe.xoxp-new", "refresh_token": "xoxe-new"})
def test_rotate_refresh_token_success(mock_rj):
    with patch("api.infrastructure.slack.config_token.validate_config_access_token"):
        access, refresh = rotate_refresh_token("xoxe-old")
    assert access == "xoxe.xoxp-new"
    assert refresh == "xoxe-new"


@patch(_TRANSPORT, return_value={"ok": False, "error": "token_expired"})
def test_rotate_refresh_token_failure(mock_rj):
    with pytest.raises(HTTPException) as exc:
        rotate_refresh_token("xoxe-old")
    assert exc.value.status_code == 400
    assert "token_expired" in exc.value.detail


@patch("api.infrastructure.slack.config_token.rotate_refresh_token", return_value=("access", "refresh"))
def test_validate_config_credential_refresh_token(mock_rotate):
    access, refresh = validate_config_credential("xoxe-something")
    mock_rotate.assert_called_once_with("xoxe-something")
    assert access == "access"
    assert refresh == "refresh"


@patch("api.infrastructure.slack.config_token.validate_config_access_token")
def test_validate_config_credential_access_token(mock_validate):
    access, refresh = validate_config_credential("some-access-token")
    mock_validate.assert_called_once_with("some-access-token")
    assert access == "some-access-token"
    assert refresh is None


@patch(_TRANSPORT, return_value={"ok": True, "app_id": "A12345"})
def test_create_slack_app_success(mock_rj):
    app_id = create_slack_app("access-token", {"display_information": {"name": "Test"}})
    assert app_id == "A12345"


@patch(_TRANSPORT, return_value={"ok": False, "error": "invalid_auth"})
def test_create_slack_app_invalid_auth(mock_rj):
    with pytest.raises(HTTPException) as exc:
        create_slack_app("bad-token", {})
    assert exc.value.status_code == 400
    assert "invalid or expired" in exc.value.detail
```

**Verify:** `cd api && uv run python -m pytest tests/unit/test_slack_config_token.py -v` — all 8 tests FAIL (module not found).

### 2b. IMPLEMENT: `api/infrastructure/slack/config_token.py`

```python
"""Slack App Configuration Token validation, rotation, and app creation."""
import json
import logging
import urllib.parse

from fastapi import HTTPException, status

from api.infrastructure.slack.transport import request_json

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"

_VALIDATION_MANIFEST: dict = {
    "display_information": {
        "name": "Agent Farm Validation",
        "description": "Temporary manifest validation",
    },
    "features": {
        "app_home": {"home_tab_enabled": False, "messages_tab_enabled": True, "messages_tab_read_only_enabled": False},
        "bot_user": {"display_name": "Agent Farm Validation", "always_online": False},
    },
    "oauth_config": {"scopes": {"bot": ["chat:write"]}},
    "settings": {
        "event_subscriptions": {"bot_events": ["message.im"]},
        "interactivity": {"is_enabled": True},
        "org_deploy_enabled": False,
        "socket_mode_enabled": True,
        "token_rotation_enabled": False,
    },
}


def _post_form(token: str, method: str, data: dict[str, str]) -> dict:
    encoded = urllib.parse.urlencode(data).encode()
    return request_json(
        "POST",
        f"{_BASE}/{method}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content=encoded,
    )


def validate_config_access_token(token: str) -> None:
    if token.startswith("xapp-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That looks like an app-level token (xapp-). Slack app creation requires a configuration access token.")
    if token.startswith("xoxb-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That looks like a bot token (xoxb-). Slack app creation requires a configuration access token.")
    if token.startswith("xoxp-"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That looks like a user token (xoxp-). Slack app creation requires a configuration access token.")
    try:
        body = _post_form(token, "apps.manifest.validate", {"manifest": json.dumps(_VALIDATION_MANIFEST)})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not reach Slack to validate configuration token: {exc}") from exc
    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Slack configuration token validation failed: {error}")


def rotate_refresh_token(refresh_token: str) -> tuple[str, str]:
    try:
        body = request_json(
            "POST",
            f"{_BASE}/tooling.tokens.rotate",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urllib.parse.urlencode({"refresh_token": refresh_token}).encode(),
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not reach Slack to rotate refresh token: {exc}") from exc
    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Slack refresh token rotation failed: {error}")
    access_token = body.get("token", "")
    new_refresh_token = body.get("refresh_token", "")
    if not access_token or not new_refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slack refresh token rotation did not return a new token pair.")
    validate_config_access_token(access_token)
    return access_token, new_refresh_token


def validate_config_credential(token: str) -> tuple[str, str | None]:
    if token.startswith("xoxe-") and not token.startswith("xoxe.xoxp-"):
        return rotate_refresh_token(token)
    validate_config_access_token(token)
    return token, None


def create_slack_app(access_token: str, manifest: dict) -> str:
    try:
        body = _post_form(access_token, "apps.manifest.create", {"manifest": json.dumps(manifest)})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not reach Slack to create app: {exc}") from exc
    if not body.get("ok"):
        error = body.get("error", "unknown_error")
        if error == "invalid_auth":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slack configuration token is invalid or expired. Please update it in your account settings.",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Slack app creation failed: {error}")
    app_id = body.get("app_id", "")
    if not app_id:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Slack returned success but no app_id.")
    return app_id
```

**Verify:** Re-run `cd api && uv run python -m pytest tests/unit/test_slack_config_token.py -v` — all 8 tests PASS. Also run Step 1 tests to ensure no regression: `cd api && uv run python -m pytest tests/unit/test_slack_manifest.py -v`.

---

## Step 3: Database Model + Migration

No tests needed — this is just a schema definition. Verified by running the migration successfully.

### 3a. IMPLEMENT: Add model to `api/domains/auth/models.py`

Add at end of file. New import needed at top: `import sqlalchemy as sa` (if not already present).

```python
class UserSlackConfigToken(BaseModel, table=True):
    __tablename__: str = "user_slack_config_token"
    __table_args__ = (
        sa.UniqueConstraint("user_id", name="uq_user_slack_config_token_user"),
    )

    user_id: UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    access_token_encrypted: str = Field(nullable=False)
    refresh_token_encrypted: str = Field(nullable=False, default="")
```

Also add the request/response DTOs (using `PydanticBaseModel` which should already be imported as the Pydantic BaseModel — check existing imports):

```python
class SlackConfigTokenSave(PydanticBaseModel):
    token: str = Field(min_length=1)


class SlackConfigTokenRead(PydanticBaseModel):
    has_token: bool
    token_preview: str | None = None
```

### 3b. IMPLEMENT: Generate Alembic migration

Run `make makemigrations` (or equivalent: `cd api && uv run alembic revision --autogenerate -m "add user_slack_config_token table"`).

Verify the generated migration contains:
- `op.create_table("user_slack_config_token", ...)` with `id`, `created_at`, `updated_at`, `user_id`, `access_token_encrypted`, `refresh_token_encrypted`
- `ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE")`
- `UniqueConstraint("user_id", name="uq_user_slack_config_token_user")`

**Verify:** `make check-api` passes (Ruff). Run `make test-api` to confirm existing tests still pass with the new model in scope.

---

## Step 4: Repository

No separate unit tests — the repository is thin delegation to `PostgresRepositoryDelegate` and will be fully covered by the integration tests in Step 6. The `upsert` method uses an explicit session for the insert-or-update pattern.

### 4a. IMPLEMENT: Add `SlackConfigTokenRepository` to `api/domains/auth/repository.py`

New imports to add:
```python
from api.domains.auth.models import UserSlackConfigToken
from sqlmodel import Session, select
```

Add class below `PasswordResetTokenRepository`:

```python
@inject
@singleton
@dataclass
class SlackConfigTokenRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_user_id(self, user_id: UUID) -> UserSlackConfigToken | None:
        return self.delegate.find_one(UserSlackConfigToken, user_id=user_id)

    def upsert(
        self,
        user_id: UUID,
        access_token_encrypted: str,
        refresh_token_encrypted: str,
    ) -> UserSlackConfigToken:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(UserSlackConfigToken).where(
                    UserSlackConfigToken.user_id == user_id
                )
            ).first()
            if existing:
                existing.access_token_encrypted = access_token_encrypted
                existing.refresh_token_encrypted = refresh_token_encrypted
                session.commit()
                session.refresh(existing)
                return existing
            token = UserSlackConfigToken(
                user_id=user_id,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
            )
            session.add(token)
            session.commit()
            session.refresh(token)
            return token

    def delete_by_user_id(self, user_id: UUID) -> bool:
        return self.delegate.delete_all(UserSlackConfigToken, user_id=user_id)
```

**Verify:** `make check-api` passes. `make test-api` still passes (no regressions).

---

## Step 5: Service Implementation

No separate unit tests — the service is fully covered by the integration tests in Step 6. The service orchestrates encryption, validation, and storage.

### 5a. IMPLEMENT: `api/domains/auth/slack_config_token_service.py`

```python
"""Service for managing per-user Slack configuration tokens."""
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.auth.models import SlackConfigTokenRead
from api.domains.auth.repository import SlackConfigTokenRepository
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.slack.config_token import (
    rotate_refresh_token,
    validate_config_credential,
)

logger = logging.getLogger(__name__)


def _mask_token(token: str) -> str:
    if len(token) <= 12:
        return token[:4] + "****"
    return token[:5] + "****" + token[-4:]


@inject
@singleton
@dataclass
class SlackConfigTokenService:
    repository: SlackConfigTokenRepository
    config: Config

    def get_config_token_read(self, user_id: UUID) -> SlackConfigTokenRead:
        record = self.repository.get_by_user_id(user_id)
        if not record:
            return SlackConfigTokenRead(has_token=False, token_preview=None)
        try:
            access = decrypt_token(
                record.access_token_encrypted,
                self.config.agent_token_encryption_key,
            )
            preview = _mask_token(access)
        except Exception:
            preview = "****"
        return SlackConfigTokenRead(has_token=True, token_preview=preview)

    def save_config_token(self, user_id: UUID, raw_token: str) -> SlackConfigTokenRead:
        raw = raw_token.strip()
        if not raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token cannot be empty.",
            )
        access_token, refresh_token = validate_config_credential(raw)
        key = self.config.agent_token_encryption_key
        self.repository.upsert(
            user_id=user_id,
            access_token_encrypted=encrypt_token(access_token, key),
            refresh_token_encrypted=encrypt_token(refresh_token, key) if refresh_token else "",
        )
        return SlackConfigTokenRead(
            has_token=True,
            token_preview=_mask_token(access_token),
        )

    def get_usable_access_token(self, user_id: UUID) -> str:
        record = self.repository.get_by_user_id(user_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Slack configuration token found. Save one in your account settings first.",
            )
        key = self.config.agent_token_encryption_key
        if record.refresh_token_encrypted:
            try:
                refresh = decrypt_token(record.refresh_token_encrypted, key)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Stored refresh token is corrupted. Please re-save your configuration token.",
                ) from exc
            new_access, new_refresh = rotate_refresh_token(refresh)
            self.repository.upsert(
                user_id=user_id,
                access_token_encrypted=encrypt_token(new_access, key),
                refresh_token_encrypted=encrypt_token(new_refresh, key),
            )
            return new_access
        try:
            return decrypt_token(record.access_token_encrypted, key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stored access token is corrupted. Please re-save your configuration token.",
            ) from exc

    def delete_config_token(self, user_id: UUID) -> None:
        self.repository.delete_by_user_id(user_id)
```

**Verify:** `make check-api` passes. `make test-api` still passes (no regressions).

---

## Step 6: Auth Routes — Integration Tests then Implementation

Integration tests use the project's BDD `given`/`when`/`then` framework with real DB (testcontainers) and mocked Slack calls.

### 6a. TEST: `api/tests/integration/test_slack_config_token.py`

```python
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to, is_not, none
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_authenticated_user

_VALIDATE = "api.infrastructure.slack.config_token.validate_config_credential"
_URL = "/api/v1/auth/me/slack-config-token"


def test_get_slack_config_token_when_none_stored():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_authenticated_user(email="user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client
        headers = {"Authorization": f"Bearer {context.access_token}"}

        with when("I GET my slack config token"):
            response = client.get(_URL, headers=headers)

            with then("it should indicate no token"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(False))
                assert_that(body["token_preview"], none())


@patch(_VALIDATE, return_value=("valid-access-token", None))
def test_save_and_get_slack_config_token(mock_validate):
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_authenticated_user(email="user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client
        headers = {"Authorization": f"Bearer {context.access_token}"}

        with when("I save a config token"):
            response = client.put(_URL, json={"token": "valid-access-token"}, headers=headers)

            with then("it should return has_token=true with preview"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(True))
                assert_that(body["token_preview"], is_not(none()))

        with when("I GET my slack config token"):
            response = client.get(_URL, headers=headers)

            with then("it should still have the token"):
                assert_that(response.status_code, equal_to(status.HTTP_200_OK))
                body = response.json()
                assert_that(body["has_token"], equal_to(True))


def test_save_slack_config_token_rejects_xoxb():
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_authenticated_user(email="user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client
        headers = {"Authorization": f"Bearer {context.access_token}"}

        with when("I try to save a bot token"):
            response = client.put(_URL, json={"token": "xoxb-fake-token"}, headers=headers)

            with then("it should be rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@patch(_VALIDATE, return_value=("valid-access-token", None))
def test_delete_slack_config_token(mock_validate):
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_authenticated_user(email="user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client
        headers = {"Authorization": f"Bearer {context.access_token}"}

        with when("I save then delete a config token"):
            client.put(_URL, json={"token": "valid-access-token"}, headers=headers)
            response = client.delete(_URL, headers=headers)

            with then("delete should return 204"):
                assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

            with then("GET should show no token"):
                response = client.get(_URL, headers=headers)
                body = response.json()
                assert_that(body["has_token"], equal_to(False))


def test_slack_config_token_requires_auth():
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

        with when("I GET without auth"):
            response = client.get(_URL)

            with then("it should be 401"):
                assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
```

**Verify:** `cd api && uv run python -m pytest tests/integration/test_slack_config_token.py -v` — all tests FAIL (routes don't exist yet).

### 6b. IMPLEMENT: Modify `api/domains/auth/routes.py`

Add imports at top:
```python
from api.domains.auth.models import SlackConfigTokenRead, SlackConfigTokenSave
from api.domains.auth.slack_config_token_service import SlackConfigTokenService
```

Add 3 endpoints at end of file:
```python
@auth_router.get("/me/slack-config-token", response_model=SlackConfigTokenRead)
def get_slack_config_token(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: SlackConfigTokenService = Injected(SlackConfigTokenService),
) -> SlackConfigTokenRead:
    return service.get_config_token_read(context.user.id)


@auth_router.put("/me/slack-config-token", response_model=SlackConfigTokenRead)
def save_slack_config_token(
    body: SlackConfigTokenSave,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: SlackConfigTokenService = Injected(SlackConfigTokenService),
) -> SlackConfigTokenRead:
    return service.save_config_token(context.user.id, body.token)


@auth_router.delete("/me/slack-config-token", status_code=status.HTTP_204_NO_CONTENT)
def delete_slack_config_token(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: SlackConfigTokenService = Injected(SlackConfigTokenService),
) -> None:
    service.delete_config_token(context.user.id)
```

**Verify:** Re-run `cd api && uv run python -m pytest tests/integration/test_slack_config_token.py -v` — all 5 tests PASS.

Cumulative check: `make test-api` — all existing + new tests pass.

---

## Step 7: Slack App Creation Route + Registration

No separate test file — we add one integration test to the existing Step 6 test file, then implement the route.

### 7a. TEST: Add to `api/tests/integration/test_slack_config_token.py`

```python
@patch(_VALIDATE, return_value=("valid-access-token", None))
@patch("api.infrastructure.slack.config_token.create_slack_app", return_value="A12345")
def test_create_slack_app_via_api(mock_create, mock_validate):
    with given(
        [
            prepare_injector(),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_authenticated_user(email="user@example.com", password="password"),
        ]
    ) as context:
        client: TestClient = context.client
        headers = {"Authorization": f"Bearer {context.access_token}"}

        # First save a config token
        client.put(_URL, json={"token": "valid-access-token"}, headers=headers)

        with when("I create a slack app"):
            response = client.post(
                "/api/v1/slack/apps",
                json={"name": "TestBot", "description": "A test bot"},
                headers=headers,
            )

            with then("it should return app_id and URLs"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                body = response.json()
                assert_that(body["app_id"], equal_to("A12345"))
                assert "A12345" in body["bot_token_url"]
                assert "A12345" in body["app_token_url"]
```

**Verify:** This test FAILS (route doesn't exist yet).

### 7b. IMPLEMENT: `api/infrastructure/slack/routes.py`

```python
"""Slack app management routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.slack_config_token_service import SlackConfigTokenService
from api.domains.auth.utils import get_current_user
from api.infrastructure.slack.config_token import create_slack_app
from api.infrastructure.slack.manifest import build_slack_app_manifest

slack_router = APIRouter(prefix="/slack", tags=["slack"])


class CreateSlackAppRequest(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=300, default="")
    background_color: str = Field(default="#4A154B", max_length=7)


class CreateSlackAppResponse(PydanticBaseModel):
    app_id: str
    bot_token_url: str
    app_token_url: str


@slack_router.post("/apps", response_model=CreateSlackAppResponse, status_code=status.HTTP_201_CREATED)
def create_slack_app_route(
    body: CreateSlackAppRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    token_service: SlackConfigTokenService = Injected(SlackConfigTokenService),
) -> CreateSlackAppResponse:
    access_token = token_service.get_usable_access_token(context.user.id)
    manifest = build_slack_app_manifest(
        name=body.name,
        description=body.description,
        background_color=body.background_color,
    )
    app_id = create_slack_app(access_token, manifest)
    return CreateSlackAppResponse(
        app_id=app_id,
        bot_token_url=f"https://api.slack.com/apps/{app_id}/oauth",
        app_token_url=f"https://api.slack.com/apps/{app_id}/general",
    )
```

### 7c. IMPLEMENT: Register router in `api/api_app.py`

Add import:
```python
from api.infrastructure.slack.routes import slack_router
```

Add after existing `subapi.include_router(users_router)`:
```python
subapi.include_router(slack_router)
```

**Verify:** Re-run `cd api && uv run python -m pytest tests/integration/test_slack_config_token.py -v` — all 6 tests PASS.

Full backend check: `make check-api && make test-api` — everything green.

---

## Step 8: UI — Schemas, Query Keys, Hooks

No tests needed — verified by TypeScript type checking. These are pure type definitions and API bindings.

**Key convention:** The API client at `ui/src/shared/api` auto-transforms keys via `humps`:
- **Requests:** camelCase → snake_case (e.g., `backgroundColor` → `background_color`)
- **Responses:** snake_case → camelCase (e.g., `app_id` → `appId`, `has_token` → `hasToken`)

So TypeScript types and Zod schemas use **camelCase**, and the backend uses **snake_case**. The transform is automatic — no manual conversion needed.

### 8a. IMPLEMENT: Modify `ui/src/shared/query-keys.ts`

Add at end:
```ts
export const slackConfigTokenKey = createQueryKeyStructure("slack-config-token");
```

### 8b. IMPLEMENT: `ui/src/features/account/schemas.ts`

```ts
import { z } from "zod";

export const slackConfigTokenReadSchema = z.object({
  hasToken: z.boolean(),
  tokenPreview: z.string().nullable(),
});

export type SlackConfigTokenRead = z.infer<typeof slackConfigTokenReadSchema>;

export const createSlackAppResponseSchema = z.object({
  appId: z.string(),
  botTokenUrl: z.string(),
  appTokenUrl: z.string(),
});

export type CreateSlackAppResponse = z.infer<typeof createSlackAppResponseSchema>;
```

### 8c. IMPLEMENT: `ui/src/features/account/hooks/use-slack-config-token.ts`

```ts
import { useQuery } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { slackConfigTokenKey } from "@/shared/query-keys";
import {
  slackConfigTokenReadSchema,
  type SlackConfigTokenRead,
} from "@/features/account/schemas";

export function useSlackConfigToken() {
  const query = useQuery({
    queryKey: slackConfigTokenKey.detail("me"),
    queryFn: () =>
      api.get<SlackConfigTokenRead>("/api/v1/auth/me/slack-config-token", {
        schema: slackConfigTokenReadSchema,
      }),
  });

  return {
    hasToken: query.data?.data?.hasToken ?? false,
    tokenPreview: query.data?.data?.tokenPreview ?? null,
    isLoading: query.isLoading,
    error: query.error,
  };
}
```

### 8d. IMPLEMENT: `ui/src/features/account/hooks/use-slack-config-token-actions.ts`

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { slackConfigTokenKey } from "@/shared/query-keys";
import {
  slackConfigTokenReadSchema,
  type SlackConfigTokenRead,
} from "@/features/account/schemas";

export function useSlackConfigTokenActions() {
  const queryClient = useQueryClient();

  const saveToken = useMutation({
    mutationFn: (token: string) =>
      api.put<SlackConfigTokenRead>("/api/v1/auth/me/slack-config-token", { token }, {
        schema: slackConfigTokenReadSchema,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: slackConfigTokenKey.all });
    },
  });

  const deleteToken = useMutation({
    mutationFn: () => api.delete("/api/v1/auth/me/slack-config-token"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: slackConfigTokenKey.all });
    },
  });

  return { saveToken, deleteToken };
}
```

### 8e. IMPLEMENT: `ui/src/features/agents/hooks/use-create-slack-app.ts`

```ts
import { useMutation } from "@tanstack/react-query";

import { api } from "@/shared/api";
import {
  createSlackAppResponseSchema,
  type CreateSlackAppResponse,
} from "@/features/account/schemas";

export type CreateSlackAppData = {
  name: string;
  description: string;
  backgroundColor: string;
};

export function useCreateSlackApp() {
  return useMutation({
    mutationFn: (data: CreateSlackAppData) =>
      api.post<CreateSlackAppResponse>("/api/v1/slack/apps", data, {
        schema: createSlackAppResponseSchema,
      }),
  });
}
```

**Verify:** `cd ui && pnpm -s tsc --noEmit` — no type errors.

---

## Step 9: UI — Account Page

No tests required — this is a new page with straightforward UI. Verified by TypeScript type checking and manual visual inspection.

### 9a. IMPLEMENT: `ui/src/features/account/components/slack-token-section.tsx`

A section component with 3 states:
- **No token saved:** Instructions + token input + "Save" button
- **Token saved:** Masked preview + "Update" / "Remove" buttons
- **Editing:** Token input + "Save" / "Cancel" buttons

Uses `useSlackConfigToken()` and `useSlackConfigTokenActions()` hooks internally.

Instructions content:
```
To automate Slack app creation, you need a configuration access token.
1. Go to api.slack.com/apps
2. Click any app (or create a temporary one)
3. Go to "Basic Information" → scroll to "App Configuration Tokens"
4. Click "Generate Token" to create a configuration access token
5. Copy and paste it below
```

### 9b. IMPLEMENT: `ui/src/features/account/components/account-page.tsx`

Layout: heading "Account" + description + the `SlackTokenSection`. Uses the same max-width container pattern as the settings page.

### 9c. IMPLEMENT: `ui/src/app/dashboard/account/page.tsx`

```tsx
import { AccountPage } from "@/features/account/components/account-page";

export default function AccountRoute() {
  return <AccountPage />;
}
```

### 9d. IMPLEMENT: Wire navigation in `ui/src/components/top-nav.tsx`

Change the Account `<button>` (lines 132-136) to a `<Link>`:

**Before:**
```tsx
<button className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
  style={{ color: "var(--ink-2)" }}
>
  <UserIcon /> Account
</button>
```

**After:**
```tsx
<Link
  href="/dashboard/account"
  className="af-hover-bg w-full text-left flex items-center gap-2.5 px-3.5 py-2 text-[13.5px]"
  style={{ color: "var(--ink-2)" }}
  onClick={() => setMenuOpen(false)}
>
  <UserIcon /> Account
</Link>
```

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes. Start dev server, navigate to `/dashboard/account`, verify page renders. Click Account in user menu dropdown, verify navigation works.

---

## Step 10: UI — Wizard Step Type + Manifest Scope Update

Small, isolated change. Extends the step type union and updates the client-side manifest to match the expanded scopes.

### 10a. IMPLEMENT: Modify `ui/src/features/agents/components/hire-dialog-steps.tsx`

**Change 1:** Add `"config-token"` to `WizardStep` union type (line ~28-38):
```ts
export type WizardStep =
  | "template"
  | "agent-type"
  | "platform-choice"
  | "slack-choice"
  | "config-token"
  | "bot-builder"
  | "slack-tokens"
  | "teams-bot-builder"
  | "teams-credentials"
  | "details"
  | "integrations";
```

**Change 2:** Update `generateManifest()` function — replace the `bot` scopes array and `bot_events` array with the full lists from `api/infrastructure/slack/manifest.py` (Step 1b). This aligns the manual-path manifest with the automated-path manifest.

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes. Existing wizard flows still work.

---

## Step 11: UI — ConfigTokenStep Component

New component added to `hire-dialog-steps.tsx`.

### 11a. IMPLEMENT: Add `ConfigTokenStep` to `hire-dialog-steps.tsx`

Props:
```ts
{
  tokenInput: string;
  onTokenInputChange: (v: string) => void;
  showToken: boolean;
  onToggleToken: () => void;
  isSaving: boolean;
  error: string | null;
}
```

Renders:
1. Explanation text: "To create the Slack app automatically, you need a configuration access token."
2. Numbered steps using existing `NextStep` component with link to `api.slack.com/apps`
3. `FormField` with `TokenInput` for the config token (placeholder: "xoxe-...")
4. Error display if `error` is not null
5. Note: "This token is saved to your account and reused for future bot creation." with link to `/dashboard/account`

The footer button ("Save & continue") is rendered in `hire-dialog.tsx`, not here.

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes.

---

## Step 12: UI — BotBuilderStep `automated` Prop

### 12a. IMPLEMENT: Modify `BotBuilderStep` in `hire-dialog-steps.tsx`

Add optional prop: `automated?: boolean` (defaults to `false`).

When `automated` is `true`:
- Show only name, description, color inputs
- Hide the "Generated manifest" section (`{!automated && ( ... )}`)
- Hide the "What to do next" manual instructions card (`{!automated && ( ... )}`)

When `automated` is `false`: render exactly the current UI, unchanged.

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes. Start dev server, test the existing "Set up new bot" flow — manual path still shows manifest + instructions.

---

## Step 13: UI — SlackTokensStep Direct-Link Props

### 13a. IMPLEMENT: Modify `SlackTokensStep` in `hire-dialog-steps.tsx`

Add optional props: `appId?: string | null`, `botTokenUrl?: string | null`, `appTokenUrl?: string | null`.

When `appId` is truthy, show a different instructions card above the token inputs:
- "Your Slack app is created!" heading
- `NextStep 1:` Install and copy Bot Token → link to `botTokenUrl`
- `NextStep 2:` Generate App-Level Token → link to `appTokenUrl`
- `NextStep 3:` Paste both tokens below

When `appId` is null/undefined: render the existing UI unchanged.

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes. Existing "I already have a Slack app" path still works (no appId passed → unchanged UI).

---

## Step 14: UI — Wizard Orchestrator Changes

The most complex UI step. Modifies `hire-dialog.tsx` to wire everything together.

### 14a. IMPLEMENT: Modify `ui/src/features/agents/components/hire-dialog.tsx`

**New imports:**
```ts
import { useSlackConfigToken } from "@/features/account/hooks/use-slack-config-token";
import { useSlackConfigTokenActions } from "@/features/account/hooks/use-slack-config-token-actions";
import { useCreateSlackApp } from "../hooks/use-create-slack-app";
// Add ConfigTokenStep to the existing import from "./hire-dialog-steps"
```

**New state variables** (after existing state):
```ts
const { hasToken: hasConfigToken, isLoading: isLoadingConfigToken } = useSlackConfigToken();
const { saveToken } = useSlackConfigTokenActions();
const createSlackApp = useCreateSlackApp();

const [configTokenInput, setConfigTokenInput] = useState("");
const [showConfigToken, setShowConfigToken] = useState(false);
const [configTokenError, setConfigTokenError] = useState<string | null>(null);
const [slackAppId, setSlackAppId] = useState<string | null>(null);
const [botTokenUrl, setBotTokenUrl] = useState<string | null>(null);
const [appTokenUrl, setAppTokenUrl] = useState<string | null>(null);
const [isCreatingApp, setIsCreatingApp] = useState(false);
const [createAppError, setCreateAppError] = useState<string | null>(null);
const [configTokenReady, setConfigTokenReady] = useState(false);
```

**Sync effect:**
```ts
useEffect(() => {
  if (!isLoadingConfigToken && hasConfigToken) {
    setConfigTokenReady(true);
  }
}, [isLoadingConfigToken, hasConfigToken]);
```

**Modify `getSteps()`** — add `configTokenReady: boolean` parameter. Full rewrite:

```ts
function getSteps(
  agentType: "openclaw" | "hermes",
  platform: "slack" | "teams",
  setupNewBot: boolean,
  configTokenReady: boolean,
): WizardStep[] {
  if (agentType === "hermes") {
    if (!setupNewBot) {
      // "I already have a Slack app" — unchanged
      return ["template", "agent-type", "slack-choice", "slack-tokens", "details", "integrations"];
    }
    // "Set up a new Slack bot" with automation
    const base: WizardStep[] = ["template", "agent-type", "slack-choice"];
    if (!configTokenReady) base.push("config-token");
    base.push("bot-builder", "slack-tokens", "details", "integrations");
    return base;
  }
  if (platform === "teams") {
    // Teams path — completely unchanged
    return ["template", "agent-type", "platform-choice", "teams-credentials", "teams-bot-builder", "details", "integrations"];
  }
  // OpenClaw + Slack
  if (!setupNewBot) {
    return ["template", "agent-type", "platform-choice", "slack-choice", "slack-tokens", "details", "integrations"];
  }
  const base: WizardStep[] = ["template", "agent-type", "platform-choice", "slack-choice"];
  if (!configTokenReady) base.push("config-token");
  base.push("bot-builder", "slack-tokens", "details", "integrations");
  return base;
}
```

**Add `stepTitle` case:** `"config-token"` → `"Set up Slack app creation"`.

**Update all `getSteps()` / `stepOrdinal()` call sites** to pass `configTokenReady`. Also update `stepOrdinal` function signature to accept and forward the extra parameter.

**Add `handleSaveConfigToken` handler:** validates input → calls `saveToken.mutateAsync()` → sets `configTokenReady(true)` → advances to `"bot-builder"`. On error, sets `configTokenError`.

**Add `handleContinueFromBotBuilder` handler:** if `configTokenReady && setupNewBot` → calls `createSlackApp.mutateAsync()` → stores `slackAppId`, `botTokenUrl`, `appTokenUrl` → advances to `"slack-tokens"`. On error, sets `createAppError`. If not automated → just advances to `"slack-tokens"` (existing manual path).

**Render changes:**
- Add `ConfigTokenStep` render block for `step === "config-token"`
- Pass `automated={configTokenReady && setupNewBot}` to `BotBuilderStep`
- Pass `appId={slackAppId}`, `botTokenUrl`, `appTokenUrl` to `SlackTokensStep`
- Add footer button for `"config-token"` step: "Save & continue" / "Validating…"
- Modify `"bot-builder"` footer button to use `handleContinueFromBotBuilder`: "Continue" / "Creating app…"
- Show `createAppError` below bot-builder content if set

**Verify:** `cd ui && pnpm -s tsc --noEmit` passes. Then manual testing of all paths:
1. **Automated:** Hire agent → Slack → "Set up new bot" → (config-token step if no saved token) → bot-builder (simplified) → Continue creates app → slack-tokens with direct links → complete flow
2. **Manual ("I already have an app"):** Hire agent → Slack → "I already have a Slack app" → slack-tokens (unchanged) → complete flow
3. **Teams:** Hire agent → Teams → unchanged flow
4. **Existing agents:** start/stop/update all work

---

## Step 15: Final Full-Suite Verification

Run everything end-to-end.

```
# Backend
make check-api         # Ruff lint + format
make test-api          # All unit + integration tests

# Frontend
cd ui && pnpm -s tsc --noEmit   # TypeScript
make lint-ui                      # ESLint
```

Manual smoke tests:
1. Save config token on Account page → verify masked preview
2. Hire agent with automated flow → app created → direct links shown → tokens entered → agent created
3. "I already have a Slack app" flow → identical to pre-change
4. Teams flow → identical to pre-change
5. Existing agents → conversations, tool calls, start/stop all work

---

## Files Summary

### New files (in creation order)
| Step | File | Purpose |
|------|------|---------|
| 1a | `api/tests/unit/test_slack_manifest.py` | Tests for manifest builder |
| 1b | `api/infrastructure/slack/manifest.py` | Manifest builder with expanded scopes/events |
| 2a | `api/tests/unit/test_slack_config_token.py` | Tests for Slack API infrastructure functions |
| 2b | `api/infrastructure/slack/config_token.py` | Validate/rotate config tokens, create apps |
| 3a | `api/domains/auth/models.py` (modify) | `UserSlackConfigToken` model + DTOs |
| 3b | `api/migrations/versions/<hash>_...py` | DB migration |
| 4a | `api/domains/auth/repository.py` (modify) | `SlackConfigTokenRepository` |
| 5a | `api/domains/auth/slack_config_token_service.py` | Token management service |
| 6a | `api/tests/integration/test_slack_config_token.py` | Integration tests for auth routes |
| 6b | `api/domains/auth/routes.py` (modify) | 3 config token endpoints |
| 7a | (add to 6a) | Integration test for app creation route |
| 7b | `api/infrastructure/slack/routes.py` | `POST /api/v1/slack/apps` endpoint |
| 7c | `api/api_app.py` (modify) | Register `slack_router` |
| 8a-e | UI hooks/schemas/query-keys | API bindings (5 files) |
| 9a-d | UI account page + nav | Account page (3 new files + 1 modify) |
| 10-13 | UI step components | Wizard step modifications |
| 14 | `hire-dialog.tsx` (modify) | Wizard orchestrator |

### Modified files
| File | Change |
|------|--------|
| `api/domains/auth/models.py` | Add `UserSlackConfigToken`, DTOs |
| `api/domains/auth/repository.py` | Add `SlackConfigTokenRepository` |
| `api/domains/auth/routes.py` | Add 3 config token endpoints |
| `api/api_app.py` | Register `slack_router` |
| `ui/src/components/top-nav.tsx` | Wire Account link |
| `ui/src/shared/query-keys.ts` | Add `slackConfigTokenKey` |
| `ui/src/features/agents/components/hire-dialog-steps.tsx` | Add step type, ConfigTokenStep, modify BotBuilderStep + SlackTokensStep, update scopes |
| `ui/src/features/agents/components/hire-dialog.tsx` | Orchestrator: state, handlers, step logic, rendering |
