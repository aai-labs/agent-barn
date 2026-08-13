from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, has_items, not_
from starlette.testclient import TestClient

from api.domains.rbac.catalog import PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    skill_is_assigned_to_agent,
    there_is_a_skill,
    there_is_a_skill_for_another_org,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.template import there_is_a_template, there_is_a_template_skill
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/skills"
_PLATFORM_BASE = "/api/v1/platform/skills"

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


def _there_is_a_role_actor(role: OrganizationRole):
    def step(context):
        user_id = uuid7()
        there_is_a_user(
            id=user_id,
            email=f"{role.value.lower()}-skills@example.com",
            role=role,
        )(context)
        there_is_an_access_token_for_user(user_id=user_id)(context)

    return step


def _there_is_a_member_actor():
    return _there_is_a_role_actor(OrganizationRole.MEMBER)


def _files(path: str = "SKILL.md", content: str = "# Skill") -> list[dict]:
    return [{"path": path, "content": content}]


def test_member_cannot_create_skill():
    with given([*_GIVEN, _there_is_a_member_actor()]) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Member Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_skill_manage_cannot_create_skill():
    with given(
        [
            *_GIVEN,
            _there_is_a_role_actor(OrganizationRole.ADMIN),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.SKILL_MANAGE),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Blocked Admin Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_with_assigned_skill_manage_cannot_create_skill():
    with given(
        [
            *_GIVEN,
            _there_is_a_role_actor(OrganizationRole.ADMIN),
            role_lacks_permission(
                OrganizationRole.ADMIN,
                PermissionKey.SKILL_MANAGE,
            ),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Assigned Admin Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_can_create_skill():
    with given([*_GIVEN, _there_is_a_role_actor(OrganizationRole.ADMIN)]) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Admin Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))


def test_platform_admin_without_skill_manage_permission_cannot_create_skill():
    super_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=super_id,
                email="super-skills@example.com",
                role=OrganizationRole.MEMBER,
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Platform administrator Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_create_skill_returns_201():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill"):
            response = client.post(
                _BASE,
                json={"name": "My Skill", "files": _files()},
                headers=_auth(context),
            )

        with then("it returns 201 with the skill data"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("My Skill"))
            assert_that(body["source"], equal_to("custom"))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))


def test_create_skill_requires_at_least_one_file():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with no files"):
            response = client.post(
                _BASE,
                json={"name": "Empty Skill", "files": []},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_create_skill_requires_a_skill_md_entry_point():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill whose files omit SKILL.md"):
            response = client.post(
                _BASE,
                json={"name": "No Entry", "files": _files(path="helpers/notes.md")},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("entry-point"))


def test_create_skill_with_path_traversal_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a file escaping the skill root"):
            response = client.post(
                _BASE,
                json={
                    "name": "Evil Skill",
                    "files": [
                        {"path": "SKILL.md", "content": "# Skill"},
                        {"path": "../../../etc/passwd", "content": "root:x:0:0:"},
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_absolute_path_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with an absolute file path"):
            response = client.post(
                _BASE,
                json={
                    "name": "Absolute Skill",
                    "files": [
                        {"path": "SKILL.md", "content": "# Skill"},
                        {"path": "/etc/passwd", "content": "root:x:0:0:"},
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_create_skill_with_duplicate_paths_returns_400():
    """Two entries differing only in case would collide on the agent's Linux filesystem."""
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with case-colliding paths"):
            response = client.post(
                _BASE,
                json={
                    "name": "Dup Skill",
                    "files": [
                        {"path": "SKILL.md", "content": "# Skill"},
                        {"path": "skill.MD", "content": "# Other"},
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("Duplicate"))


def test_create_skill_with_oversized_file_returns_400():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a skill with a file above the 1 MB limit"):
            response = client.post(
                _BASE,
                json={"name": "Big Skill", "files": _files(content="x" * (1024 * 1024 + 1))},
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
                json={"name": "Skill", "files": _files()},
            )

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_member_without_skill_read_cannot_list_skills():
    with given(
        [
            *_GIVEN,
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.SKILL_READ),
        ]
    ) as context:
        response = context.client.get(_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_can_list_shared_skills():
    with given([*_GIVEN, there_is_a_skill(name="Shared Skill"), _there_is_a_member_actor()]) as context:
        response = context.client.get(_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["items"][0]["name"], equal_to("Shared Skill"))


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
            names = [s["name"] for s in response.json()["items"]]
            assert_that(names, has_items("Org Skill", "Global Skill"))


def test_list_skills_excludes_other_org_skills():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client

        with when("I list skills"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the other org's skill is not included"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            names = [s["name"] for s in response.json()["items"]]
            assert_that(names, not_(has_item("Other Org Skill")))


def test_list_skills_returns_pagination_metadata():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Skill A"),
            there_is_a_skill(name="Skill B"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list skills"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the response includes pagination metadata"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["page"], equal_to(1))
            assert_that(body["total"], equal_to(2))


def test_list_skills_search_filter():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="GitHub Skill"),
            there_is_a_skill(name="Jira Skill"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I search for 'github'"):
            response = client.get(_BASE, params={"search": "github"}, headers=_auth(context))

        with then("only matching skills are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            names = [s["name"] for s in body["items"]]
            assert_that(names, has_item("GitHub Skill"))
            assert_that(names, not_(has_item("Jira Skill")))
            assert_that(body["total"], equal_to(1))


def test_list_skills_source_filter():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Custom Skill"),
            there_is_a_skill(name="Platform Skill", global_skill=True),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I filter by source=custom"):
            response = client.get(_BASE, params={"source": "custom"}, headers=_auth(context))

        with then("only custom skills are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            names = [s["name"] for s in body["items"]]
            assert_that(names, has_item("Custom Skill"))
            assert_that(names, not_(has_item("Platform Skill")))


def test_list_skills_pagination():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Skill 1"),
            there_is_a_skill(name="Skill 2"),
            there_is_a_skill(name="Skill 3"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I request page 1 with page_size=2"):
            response = client.get(_BASE, params={"page": 1, "page_size": 2}, headers=_auth(context))

        with then("only 2 items are returned and total reflects all skills"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(len(body["items"]), equal_to(2))
            assert_that(body["total"], equal_to(3))
            assert_that(body["page"], equal_to(1))


def test_list_skills_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list skills without auth"):
            response = client.get(_BASE)

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_platform_admin_can_list_global_skills():
    platform_admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Global Platform Skill", global_skill=True),
            there_is_a_user(
                id=platform_admin_id,
                email="platform-skill-reader@example.com",
                role=OrganizationRole.MEMBER,
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=platform_admin_id),
        ]
    ) as context:
        response = context.client.get(_PLATFORM_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that([skill["name"] for skill in response.json()], has_item("Global Platform Skill"))


def test_non_platform_admin_cannot_list_global_skills():
    with given([*_GIVEN, there_is_a_skill(name="Global Platform Skill", global_skill=True)]) as context:
        response = context.client.get(_PLATFORM_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_without_skill_read_cannot_get_skill():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Hidden Skill"),
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.SKILL_READ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


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
            response = client.get(f"{_BASE}/{context.other_org_skill.id}", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_skill_requires_auth():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I get a skill without auth"):
            response = client.get(f"{_BASE}/{context.skill.id}")

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_member_cannot_update_skill():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Member Cannot Update"),
            _there_is_a_member_actor(),
        ]
    ) as context:
        response = context.client.patch(
            f"{_BASE}/{context.skill.id}",
            json={"name": "Changed"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


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


def test_update_skill_metadata_only_does_not_publish_a_version():
    """PATCH /{skill_id} is metadata-only; content changes go through the draft
    flow, so it must never inflate version history or make running agents look
    out of date."""
    with given([*_GIVEN, there_is_a_skill(name="Stable Skill")]) as context:
        client: TestClient = context.client

        with when("I update only the skill name"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"name": "Renamed Skill"},
                headers=_auth(context),
            )

        with then("the version is unchanged"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["version"], equal_to(1))


def test_renaming_a_skill_does_not_move_its_mount_directory():
    """root_dir is baked into pointers and into cross-references inside the skill's own
    markdown, so a rename must not relocate the files."""
    with given([*_GIVEN, there_is_a_skill(name="Original Name")]) as context:
        client: TestClient = context.client
        original_root = context.skill.root_dir

        with when("I rename the skill"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}",
                json={"name": "Completely Different"},
                headers=_auth(context),
            )

        with then("the slug and mount directory are unchanged"):
            body = response.json()
            assert_that(body["name"], equal_to("Completely Different"))
            assert_that(body["root_dir"], equal_to(original_root))
            assert_that(body["slug"], equal_to(context.skill.slug))


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
            response = client.patch(f"{_BASE}/{context.skill.id}", json={"name": "New Name"})

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def _publish_new_version(client: TestClient, context, content: str) -> None:
    """Draft -> update -> publish, the only path to a new skill version."""
    client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))
    client.patch(
        f"{_BASE}/{context.skill.id}/draft",
        json={"files": _files(content=content)},
        headers=_auth(context),
    )
    client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))


def test_list_skill_versions_returns_newest_first():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")

        with when("I list the skill's versions"):
            response = client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context))

        with then("both versions are returned, newest first"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            versions = [v["version"] for v in response.json()]
            assert_that(versions, equal_to([2, 1]))


def test_list_skill_versions_requires_read_permission():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Locked Down"),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.SKILL_READ),
            _there_is_a_member_actor(),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_get_skill_version_returns_its_files():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I fetch version 1"):
            response = client.get(f"{_BASE}/{context.skill.id}/versions/1", headers=_auth(context))

        with then("it returns that version's content"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(1))
            assert_that(body["files"], equal_to([{"path": "SKILL.md", "content": "# Versioned Skill"}]))


def test_get_skill_version_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I fetch a version that was never published"):
            response = client.get(f"{_BASE}/{context.skill.id}/versions/99", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_start_skill_draft_seeds_from_latest_version():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I start a draft with no source version"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it is seeded from the latest published version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["files"], equal_to([{"path": "SKILL.md", "content": "# Versioned Skill"}]))
            assert_that(body["source_version"], equal_to(None))


def test_start_skill_draft_is_get_or_create():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))
        client.patch(
            f"{_BASE}/{context.skill.id}/draft",
            json={"files": _files(content="# In progress")},
            headers=_auth(context),
        )

        with when("I start a draft again"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("the existing in-progress draft is returned unchanged"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["files"], equal_to([{"path": "SKILL.md", "content": "# In progress"}]))


def test_skill_reads_expose_has_draft():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("no draft exists yet"):
            get_response = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))
            list_response = client.get(_BASE, headers=_auth(context))

        with then("has_draft is false everywhere"):
            assert_that(get_response.json()["has_draft"], equal_to(False))
            listed = next(s for s in list_response.json()["items"] if s["id"] == str(context.skill.id))
            assert_that(listed["has_draft"], equal_to(False))

        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("a draft is in progress"):
            get_response = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))
            list_response = client.get(_BASE, headers=_auth(context))

        with then("has_draft is true everywhere"):
            assert_that(get_response.json()["has_draft"], equal_to(True))
            listed = next(s for s in list_response.json()["items"] if s["id"] == str(context.skill.id))
            assert_that(listed["has_draft"], equal_to(True))

        client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))

        with when("the draft is published"):
            get_response = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        with then("has_draft goes back to false"):
            assert_that(get_response.json()["has_draft"], equal_to(False))


def test_start_skill_draft_with_source_version_seeds_from_that_version():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")

        with when("I start a draft seeded from version 1"):
            response = client.post(
                f"{_BASE}/{context.skill.id}/draft",
                params={"source_version": 1},
                headers=_auth(context),
            )

        with then("it carries version 1's content and remembers where it came from"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["files"], equal_to([{"path": "SKILL.md", "content": "# Versioned Skill"}]))
            assert_that(body["source_version"], equal_to(1))


def test_start_skill_draft_with_source_version_conflicts_when_a_draft_exists():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("I try to restore a version while a draft is already in progress"):
            response = client.post(
                f"{_BASE}/{context.skill.id}/draft",
                params={"source_version": 1},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_start_skill_draft_for_aai_cli_skill_returns_403():
    with given([*_GIVEN, there_is_a_skill(global_skill=True)]) as context:
        client: TestClient = context.client

        with when("I try to draft a built-in aai-cli skill"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_start_skill_draft():
    with given([*_GIVEN, there_is_a_skill(name="Member Cannot Draft"), _there_is_a_member_actor()]) as context:
        response = context.client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_get_skill_draft_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I fetch a draft that doesn't exist"):
            response = client.get(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_update_skill_draft_replaces_its_files():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("I update the draft's content"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}/draft",
                json={"files": _files(content="# Edited")},
                headers=_auth(context),
            )

        with then("the draft carries the new content, and nothing is published yet"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["files"], equal_to([{"path": "SKILL.md", "content": "# Edited"}]))

            skill_response = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context))
            assert_that(skill_response.json()["version"], equal_to(1))


def test_update_skill_draft_with_path_traversal_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("I update the draft with a file escaping the skill root"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}/draft",
                json={
                    "files": [
                        {"path": "SKILL.md", "content": "# Skill"},
                        {"path": "../../../etc/passwd", "content": "root:x:0:0:"},
                    ]
                },
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_draft_with_oversized_file_returns_400():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("I update the draft with a file above the 1 MB limit"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}/draft",
                json={"files": _files(content="x" * (1024 * 1024 + 1))},
                headers=_auth(context),
            )

        with then("it returns 400"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_update_skill_draft_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I update a draft that doesn't exist"):
            response = client.patch(
                f"{_BASE}/{context.skill.id}/draft",
                json={"files": _files()},
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_discard_skill_draft_removes_it():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with when("I discard the draft"):
            response = client.delete(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it is gone"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            get_response = client.get(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))
            assert_that(get_response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_discard_skill_draft_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I discard a draft that doesn't exist"):
            response = client.delete(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_publish_skill_draft_creates_the_next_version_and_clears_the_draft():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))
        client.patch(
            f"{_BASE}/{context.skill.id}/draft",
            json={"files": _files(content="# Rewritten")},
            headers=_auth(context),
        )

        with when("I publish the draft"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))

        with then("the published version advances, serves the new content, and the draft is cleared"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["version"], equal_to(2))

            files_response = client.get(f"{_BASE}/{context.skill.id}/files", headers=_auth(context))
            body = files_response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(body["files"], equal_to([{"path": "SKILL.md", "content": "# Rewritten"}]))

            draft_response = client.get(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))
            assert_that(draft_response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_publish_skill_draft_seeded_from_an_older_version_records_restored_from_version():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")
        client.post(f"{_BASE}/{context.skill.id}/draft", params={"source_version": 1}, headers=_auth(context))

        with when("I publish the rollback draft"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))

        with then("version 3 is published, carrying version 1's content and the restore marker"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["version"], equal_to(3))

            versions_response = client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context))
            restored_entry = next(v for v in versions_response.json() if v["version"] == 3)
            assert_that(restored_entry["restored_from_version"], equal_to(1))


def test_publish_skill_draft_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I publish a draft that doesn't exist"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_member_cannot_publish_skill_draft():
    with given([*_GIVEN, there_is_a_skill(name="Member Cannot Publish"), _there_is_a_member_actor()]) as context:
        response = context.client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_delete_skill():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Member Cannot Delete"),
            _there_is_a_member_actor(),
        ]
    ) as context:
        response = context.client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_skill_returns_204():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I delete the skill"):
            response = client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

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
            response = client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

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
            response = client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_delete_skill_requires_auth():
    with given([*_GIVEN, there_is_a_skill()]) as context:
        client: TestClient = context.client

        with when("I delete a skill without auth"):
            response = client.delete(f"{_BASE}/{context.skill.id}")

        with then("request is rejected with 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_delete_skill_required_by_template_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(),
            there_is_a_template(),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I try to delete a skill required by a template"):
            response = client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        with then("it returns 409 naming the blocking template"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(
                response.json()["detail"],
                equal_to(
                    "Skill is required by template(s): test-template. Remove it from those templates before deleting."
                ),
            )


def test_delete_skill_no_longer_required_by_latest_template_returns_204():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(),
            there_is_a_template(template_key="test-template", version=1),
            there_is_a_template_skill(),
            there_is_a_template(template_key="test-template", version=2),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I delete a skill that was required by an old template version but not the latest"):
            response = client.delete(f"{_BASE}/{context.skill.id}", headers=_auth(context))

        with then("it returns 204 because only the latest version is checked"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
