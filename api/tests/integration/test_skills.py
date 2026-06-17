import base64
import io
import zipfile
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to, has_item, has_items, not_
from starlette.testclient import TestClient

from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    MockK8sModule,
    MockLiteLLMModule,
    TEST_ENCRYPTION_KEY,
    skill_is_assigned_to_agent,
    there_is_an_agent,
    there_is_a_skill,
    there_is_a_skill_for_another_org,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/skills"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _make_zip(filename: str = "skill.md", content: str = "# Skill") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return base64.b64encode(buf.getvalue()).decode()


def _make_zip_with_path_traversal() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../etc/passwd", "root:x:0:0:root:/root:/bin/bash")
    return base64.b64encode(buf.getvalue()).decode()


def _make_high_ratio_zip() -> str:
    # 1 MB of null bytes compresses to ~1 KB → ratio ~1000x, well above the 100x limit.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.bin", b"\x00" * 1_000_000)
    return base64.b64encode(buf.getvalue()).decode()


def _make_encrypted_zip() -> str:
    # Create a valid zip then set the encryption flag (bit 0) in the central directory
    # entry so that zipfile reports flag_bits & 0x1 == 1.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skill.md", "# Skill")
    data = bytearray(buf.getvalue())
    # Central directory entry starts with PK\x01\x02; the general-purpose bit flag
    # is at byte offset 8 within that entry.
    cd_sig = b"\x50\x4b\x01\x02"
    idx = data.find(cd_sig)
    if idx != -1:
        data[idx + 8] |= 0x1
    return base64.b64encode(bytes(data)).decode()


def _make_zip_spoofed_uncompressed_size(
    file_count: int = 3, file_size: int = 500
) -> str:
    # Build a zip whose central-directory file_size fields are zeroed (metadata spoofed
    # to 0), so the header-based total check sees 0 bytes, but actual extraction of
    # file_count × file_size bytes exceeds a patched _MAX_UNCOMPRESSED_BYTES limit.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for i in range(file_count):
            zf.writestr(f"file_{i}.bin", b"\x00" * file_size)
    data = bytearray(buf.getvalue())
    for sig, compressed_off, uncompressed_off in (
        (b"\x50\x4b\x03\x04", 18, 22),
        (b"\x50\x4b\x01\x02", 20, 24),
    ):
        pos = 0
        while True:
            idx = data.find(sig, pos)
            if idx == -1:
                break
            data[idx + compressed_off : idx + compressed_off + 4] = b"\x00\x00\x00\x00"
            data[idx + uncompressed_off : idx + uncompressed_off + 4] = (
                b"\x00\x00\x00\x00"
            )
            pos = idx + 1
    return base64.b64encode(bytes(data)).decode()


_VALID_CREATE = {
    "name": "My Skill",
    "zip_content": None,
}


def test_create_skill_returns_201():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill"):
            response = client.post(
                _BASE,
                json={"name": "My Skill", "zip_content": _make_zip()},
                headers=_auth(context),
            )

        with then("it returns 201 with the skill data"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("My Skill"))
            assert_that(body["source"], equal_to("custom"))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))


def test_create_skill_with_invalid_zip_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a non-zip payload"):
            response = client.post(
                _BASE,
                json={
                    "name": "Bad Skill",
                    "zip_content": base64.b64encode(b"not a zip").decode(),
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_path_traversal_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a zip containing path traversal"):
            response = client.post(
                _BASE,
                json={
                    "name": "Evil Skill",
                    "zip_content": _make_zip_with_path_traversal(),
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_zip_bomb_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a zip bomb"):
            response = client.post(
                _BASE,
                json={
                    "name": "Bomb Skill",
                    "zip_content": _make_high_ratio_zip(),
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_encrypted_zip_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with an encrypted zip entry"):
            response = client.post(
                _BASE,
                json={
                    "name": "Encrypted Skill",
                    "zip_content": _make_encrypted_zip(),
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_oversized_zip_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a zip exceeding 50 MB"):
            response = client.post(
                _BASE,
                json={
                    "name": "Big Skill",
                    "zip_content": _make_zip(content="x" * (51 * 1024 * 1024)),
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_spoofed_uncompressed_size_returns_400():
    # The zip's metadata declares 0 bytes per entry (bypassing the header check), but
    # actual extraction totals 1500 bytes — above the patched 1000-byte limit.
    with patch("api.domains.skills.service._MAX_UNCOMPRESSED_BYTES", 1000):
        with given(_GIVEN) as context:
            client: TestClient = context.client

            with when(
                "I create a skill with a zip that has spoofed metadata but oversized content"
            ):
                response = client.post(
                    _BASE,
                    json={
                        "name": "Spoofed Skill",
                        "zip_content": _make_zip_spoofed_uncompressed_size(
                            file_count=3, file_size=500
                        ),
                    },
                    headers=_auth(context),
                )

            with then("it returns 400"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_without_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill without auth"):
            response = client.post(
                _BASE,
                json={"name": "Skill", "zip_content": _make_zip()},
            )

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_list_skills_returns_org_and_global_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Org Skill"),
            there_is_a_skill(name="Global Skill", global_skill=True),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list skills"):
            response = client.get(_BASE, headers=_auth(context))

        with then("both org-scoped and global skills are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            names = [s["name"] for s in response.json()]
            assert_that(names, has_items("Org Skill", "Global Skill"))


def test_list_skills_excludes_other_org_skills():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client

        with when("I list skills"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the other org's skill is not included"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            names = [s["name"] for s in response.json()]
            assert_that(names, not_(has_item("Other Org Skill")))


def test_list_skills_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list skills without auth"):
            response = client.get(_BASE)

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_skill_returns_200():
    with given([*_GIVEN, there_is_a_skill(name="Fetched Skill")]) as context:
        client: TestClient = context.client

        with when("I get the skill"):
            response = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        with then("it returns 200 with the skill data"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("Fetched Skill"))


def test_get_skill_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        from uuid import uuid4

        with when("I get a non-existent skill"):
            response = client.get(f"{_BASE}/{uuid4()}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_skill_from_another_org_returns_404():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client

        with when("I get a skill that belongs to another org"):
            response = client.get(
                f"{_BASE}/{context.other_org_skill.id}", headers=_auth(context)
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_skill_requires_auth():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I get a skill without auth"):
            response = client.get(f"{_BASE}/{context.skill.id}")

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_update_skill_returns_200():
    with given([*_GIVEN, there_is_a_skill(name="Old Name")]) as context:
        client: TestClient = context.client

        with when("I update the skill name"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"name": "New Name"},
                headers=_auth(context),
            )

        with then("it returns 200 with the updated name"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["name"], equal_to("New Name"))


def test_update_aai_cli_skill_returns_403():
    with given([*_GIVEN, there_is_a_skill(global_skill=True)]) as context:
        client: TestClient = context.client

        with when("I try to update a built-in aai-cli skill"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"name": "Hacked Name"},
                headers=_auth(context),
            )

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_update_skill_with_invalid_zip_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Valid Skill")]) as context:
        client: TestClient = context.client

        with when("I update the skill with a non-zip payload"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"zip_content": base64.b64encode(b"not a zip").decode()},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_with_path_traversal_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Valid Skill")]) as context:
        client: TestClient = context.client

        with when("I update the skill with a zip containing path traversal"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"zip_content": _make_zip_with_path_traversal()},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_with_zip_bomb_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Valid Skill")]) as context:
        client: TestClient = context.client

        with when("I update the skill with a zip bomb"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"zip_content": _make_high_ratio_zip()},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_with_spoofed_uncompressed_size_returns_400():
    with patch("api.domains.skills.service._MAX_UNCOMPRESSED_BYTES", 1000):
        with given([*_GIVEN, there_is_a_skill(name="Valid Skill")]) as context:
            client: TestClient = context.client

            with when(
                "I update the skill with a zip that has spoofed metadata but oversized content"
            ):
                response = client.patch(
                    f"{_BASE}/{context.skill.id}",
                    json={
                        "zip_content": _make_zip_spoofed_uncompressed_size(
                            file_count=3, file_size=500
                        )
                    },
                    headers=_auth(context),
                )

            with then("it returns 400"):
                assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_with_encrypted_zip_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Valid Skill")]) as context:
        client: TestClient = context.client

        with when("I update the skill with an encrypted zip entry"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"zip_content": _make_encrypted_zip()},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        from uuid import uuid4

        with when("I update a non-existent skill"):
            response = client.patch(
                f"{_BASE}/{uuid4()}",
                json={"name": "Ghost"},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_update_skill_requires_auth():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I update a skill without auth"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}", json={"name": "New Name"}
            )

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_delete_skill_returns_204():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I delete the skill"):
            response = client.delete(
                f"{_BASE}/{context.skill.id}", headers=_auth(context)
            )

        with then("it returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_delete_skill_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        from uuid import uuid4

        with when("I delete a non-existent skill"):
            response = client.delete(f"{_BASE}/{uuid4()}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_delete_aai_cli_skill_returns_403():
    with given([*_GIVEN, there_is_a_skill(global_skill=True)]) as context:
        client: TestClient = context.client

        with when("I try to delete a built-in aai-cli skill"):
            response = client.delete(
                f"{_BASE}/{context.skill.id}", headers=_auth(context)
            )

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_skill_assigned_to_agent_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I try to delete a skill that is assigned to an agent"):
            response = client.delete(
                f"{_BASE}/{context.skill.id}", headers=_auth(context)
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_delete_skill_requires_auth():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I delete a skill without auth"):
            response = client.delete(f"{_BASE}/{context.skill.id}")

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
