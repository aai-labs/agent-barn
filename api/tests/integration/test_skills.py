from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, has_items, not_, starts_with
from starlette.testclient import TestClient

from api.domains.agents.models import SecretProvider
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
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/skills"
_PLATFORM_BASE = "/api/v1/platform/skills"
_AGENT_BASE = "/api/v1/organizations/{organization_id}/agents/{agent_id}/skills"

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


def _there_is_a_skill_draft():
    def step(context):
        from api.domains.skills.repository import SkillRepository

        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save_new_draft(context.skill.id, [("SKILL.md", "# Draft")])

    return step


def _set_skill_description(description: str | None):
    def step(context):
        from api.domains.skills.repository import SkillRepository

        context.skill.description = description
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(context.skill)

    return step


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


def test_create_skill_with_duplicate_name_returns_409():
    with given([*_GIVEN, there_is_a_skill(name="Existing Skill")]) as context:
        response = context.client.post(
            _BASE,
            json={"name": "Existing Skill", "files": _files()},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("already exists"))


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


def test_aai_cli_seeder_publishes_the_bundled_skill_tree():
    with given(_GIVEN) as context:
        from api.domains.skills.repository import SkillRepository
        from api.domains.skills.skill_seeder import seed_aai_cli_skills

        repository: SkillRepository = context.injector.get(SkillRepository)
        seed_aai_cli_skills(repository)
        skills = repository.find_all_global()

        assert_that(len(skills), equal_to(14))
        for skill in skills:
            assert_that(skill.slug, starts_with("aai-"))
            assert_that(skill.root_dir, equal_to(skill.slug))
            assert_that(skill.entry_path, equal_to("SKILL.md"))
            version = repository.get_latest_version(skill.id)
            assert version is not None
            paths = [file.path for file in repository.get_files(version.id)]
            assert_that(paths, has_items("SKILL.md", "references/command-reference.md"))


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


def test_platform_admin_can_create_and_publish_platform_skill():
    platform_admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=platform_admin_id,
                email="platform-skill-author@example.com",
                role=OrganizationRole.MEMBER,
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=platform_admin_id),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.post(
            _PLATFORM_BASE,
            json={"name": "Platform Authored Skill", "files": _files(content="# Platform v1")},
            headers=_auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(body["scope"], equal_to("platform"))
        assert_that(body["version"], equal_to(None))
        assert_that(body["has_draft"], equal_to(True))
        skill_id = body["id"]

        publish = client.post(f"{_PLATFORM_BASE}/{skill_id}/draft/publish", headers=_auth(context))
        assert_that(publish.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(publish.json()["version"], equal_to(1))
        assert_that(publish.json()["has_draft"], equal_to(False))

        versions = client.get(f"{_PLATFORM_BASE}/{skill_id}/versions", headers=_auth(context))
        assert_that(versions.status_code, equal_to(status.HTTP_200_OK))
        assert_that(versions.json()[0]["is_pinned_by_agent"], equal_to(False))

        rename = client.patch(
            f"{_PLATFORM_BASE}/{skill_id}",
            json={"name": "Platform Authored Renamed"},
            headers=_auth(context),
        )
        assert_that(rename.status_code, equal_to(status.HTTP_200_OK))
        assert_that(rename.json()["name"], equal_to("Platform Authored Renamed"))


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


def test_draft_endpoints_for_another_org_skill_return_404():
    with given([*_GIVEN, there_is_a_skill_for_another_org()]) as context:
        client: TestClient = context.client
        skill_id = context.other_org_skill.id

        with when("I start a draft for another org's skill"):
            post_response = client.post(f"{_BASE}/{skill_id}/draft", headers=_auth(context))

        with then("it returns 404, not 403"):
            assert_that(post_response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

        with when("I fetch a draft for another org's skill"):
            get_response = client.get(f"{_BASE}/{skill_id}/draft", headers=_auth(context))

        with then("it returns 404"):
            assert_that(get_response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


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


def test_update_skill_rejects_draft_metadata_fields():
    with given([*_GIVEN, there_is_a_skill(name="Draft Metadata")]) as context:
        response = context.client.patch(
            f"{_BASE}/{context.skill.id}",
            json={"description": "Must be staged", "required_providers": ["github"]},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


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


def test_start_skill_draft_for_aai_cli_skill_returns_403():
    with given([*_GIVEN, there_is_a_skill(global_skill=True)]) as context:
        client: TestClient = context.client

        with when("I try to draft a built-in aai-cli skill"):
            response = client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_fork_builtin_skill_creates_org_custom_skill_seeded_from_the_builtin():
    with given([*_GIVEN, there_is_a_skill(name="Built-in Tool", global_skill=True)]) as context:
        client: TestClient = context.client
        builtin_id = str(context.skill.id)

        with when("I fork the built-in skill"):
            response = client.post(f"{_BASE}/{builtin_id}/fork", headers=_auth(context))

        with then("it creates an org-scoped custom skill seeded from the built-in"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["source"], equal_to("custom"))
            assert_that(body["organization_id"], equal_to(str(context.organization.id)))
            assert_that(body["name"], equal_to("Built-in Tool"))
            assert_that(body["root_dir"], equal_to(body["slug"]))
            assert_that(body["root_dir"], not_(equal_to("aai-cli")))
            assert_that(body["files"], equal_to([{"path": "SKILL.md", "content": "# Built-in Tool"}]))
            assert_that(body["version"], equal_to(None))
            assert_that(body["has_draft"], equal_to(True))

        with then("the fork is its own lineage and the built-in stays untouched"):
            fork = next(s for s in client.get(_BASE, headers=_auth(context)).json()["items"] if s["id"] == body["id"])
            assert_that(fork["source"], equal_to("custom"))
            builtin = client.get(f"{_BASE}/{builtin_id}", headers=_auth(context)).json()
            assert_that(builtin["source"], equal_to("aai_cli"))
            assert_that(builtin["version"], equal_to(1))
            assert_that(builtin["has_draft"], equal_to(False))


def test_forked_skill_can_apply_a_source_update_without_repinning_existing_agents():
    with given([*_GIVEN, there_is_a_skill(name="Built-in Tool", global_skill=True)]) as context:
        client: TestClient = context.client
        source_id = context.skill.id
        fork = client.post(f"{_BASE}/{source_id}/fork", headers=_auth(context)).json()
        fork_id = fork["id"]
        client.post(f"{_BASE}/{fork_id}/draft/publish", headers=_auth(context))

        from api.domains.skills.repository import SkillRepository

        repository: SkillRepository = context.injector.get(SkillRepository)
        repository.publish_version(source_id, [("SKILL.md", "# Source v2")])

        before = client.get(f"{_BASE}/{fork_id}", headers=_auth(context)).json()
        assert_that(before["update_available"], equal_to(True))

        response = client.post(f"{_BASE}/{fork_id}/source-update", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["version"], equal_to(2))
        assert_that(response.json()["source_skill_version"], equal_to(2))
        assert_that(response.json()["update_available"], equal_to(False))
        assert_that(response.json()["files"], equal_to([{"path": "SKILL.md", "content": "# Source v2"}]))

        repository.publish_version(source_id, [("SKILL.md", "# Source v3")])
        client.post(f"{_BASE}/{fork_id}/draft", headers=_auth(context))
        client.patch(
            f"{_BASE}/{fork_id}/draft",
            json={"files": _files(content="# Local draft")},
            headers=_auth(context),
        )
        draft_update = client.post(f"{_BASE}/{fork_id}/source-update", headers=_auth(context))
        assert_that(draft_update.status_code, equal_to(status.HTTP_200_OK))
        assert_that(draft_update.json()["version"], equal_to(2))
        assert_that(draft_update.json()["has_draft"], equal_to(True))
        assert_that(draft_update.json()["update_available"], equal_to(False))
        assert_that(draft_update.json()["files"], equal_to([{"path": "SKILL.md", "content": "# Source v3"}]))


def test_fork_builtin_skill_opens_a_draft_seeded_from_the_fork():
    with given([*_GIVEN, there_is_a_skill(name="Built-in Tool", global_skill=True)]) as context:
        client: TestClient = context.client
        forked = client.post(f"{_BASE}/{context.skill.id}/fork", headers=_auth(context)).json()

        with when("I fetch the fork's in-flight draft"):
            draft = client.get(f"{_BASE}/{forked['id']}/draft", headers=_auth(context))

        with then("it carries the built-in's content, ready to edit"):
            assert_that(draft.status_code, equal_to(status.HTTP_200_OK))
            assert_that(draft.json()["files"], equal_to([{"path": "SKILL.md", "content": "# Built-in Tool"}]))


def test_fork_builtin_skill_disambiguates_name_when_org_already_has_one():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Built-in Tool"),
            there_is_a_skill(name="Built-in Tool", global_skill=True),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I fork the built-in into an org that already has a same-named skill"):
            response = client.post(f"{_BASE}/{context.skill.id}/fork", headers=_auth(context))

        with then("the fork's name is disambiguated"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["name"], equal_to("Built-in Tool (fork)"))
            assert_that(response.json()["root_dir"], equal_to(response.json()["slug"]))


def test_fork_custom_skill_creates_an_independent_draft():
    with given([*_GIVEN, there_is_a_skill(name="Custom Tool")]) as context:
        with when("I fork a custom skill"):
            response = context.client.post(f"{_BASE}/{context.skill.id}/fork", headers=_auth(context))

        with then("it creates an independent draft"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["source"], equal_to("custom"))
            assert_that(response.json()["version"], equal_to(None))
            assert_that(response.json()["has_draft"], equal_to(True))


def test_agent_owner_can_create_private_skill_and_org_list_cannot_see_it():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        agent_base = _AGENT_BASE.format(organization_id=context.organization.id, agent_id=context.agent.id)
        response = context.client.post(
            agent_base,
            json={"name": "Private Skill", "files": [{"path": "SKILL.md", "content": "# Private"}]},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(body["scope"], equal_to("agent"))
        assert_that(body["agent_id"], equal_to(str(context.agent.id)))
        assert_that(body["version"], equal_to(None))
        assert_that(body["has_draft"], equal_to(True))

        org_response = context.client.get(_BASE, headers=_auth(context))
        assert_that([skill["id"] for skill in org_response.json()["items"]], not_(has_item(body["id"])))


def test_agent_owner_can_list_private_skill_with_visible_shared_skills():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_skill(name="Shared Skill")]) as context:
        agent_base = _AGENT_BASE.format(organization_id=context.organization.id, agent_id=context.agent.id)
        private = context.client.post(
            agent_base,
            json={"name": "Private Skill", "files": [{"path": "SKILL.md", "content": "# Private"}]},
            headers=_auth(context),
        ).json()

        response = context.client.get(agent_base, headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        ids = [skill["id"] for skill in response.json()["items"]]
        assert_that(ids, has_items(private["id"], str(context.skill.id)))


def test_agent_owner_can_draft_publish_read_and_prune_private_skill_versions():
    """Agent-private lifecycle endpoints must use the Agent visibility path,
    rather than accidentally falling back to Organization-owned lookup rules."""
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        agent_base = _AGENT_BASE.format(organization_id=context.organization.id, agent_id=context.agent.id)

        with when("the owner creates a private Skill and publishes its first draft"):
            created = client.post(
                agent_base,
                json={"name": "Private Lifecycle", "files": _files(content="# Private draft")},
                headers=_auth(context),
            )
            skill_id = created.json()["id"]
            draft = client.get(f"{agent_base}/{skill_id}/draft", headers=_auth(context))
            published_v1 = client.post(f"{agent_base}/{skill_id}/draft/publish", headers=_auth(context))

        with then("draft and published content remain accessible through Agent routes"):
            assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(draft.status_code, equal_to(status.HTTP_200_OK))
            assert_that(draft.json()["files"], equal_to(_files(content="# Private draft")))
            assert_that(published_v1.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(published_v1.json()["version"], equal_to(1))
            assert_that(
                client.get(f"{agent_base}/{skill_id}/versions/1", headers=_auth(context)).json()["files"],
                equal_to(_files(content="# Private draft")),
            )

        client.post(f"{agent_base}/{skill_id}/draft", headers=_auth(context))
        client.patch(
            f"{agent_base}/{skill_id}/draft",
            json={"files": _files(content="# Private v2")},
            headers=_auth(context),
        )
        published_v2 = client.post(f"{agent_base}/{skill_id}/draft/publish", headers=_auth(context))

        with when("the owner prunes an unpinned historical version"):
            deleted = client.delete(f"{agent_base}/{skill_id}/versions/1", headers=_auth(context))
            versions = client.get(f"{agent_base}/{skill_id}/versions", headers=_auth(context))

        with then("only the current immutable version remains"):
            assert_that(published_v2.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(deleted.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that([version["version"] for version in versions.json()], equal_to([2]))


def test_agent_owner_can_fork_and_apply_update_from_a_visible_shared_skill():
    with given([*_GIVEN, there_is_an_agent(), there_is_a_skill(name="Platform Source", global_skill=True)]) as context:
        client: TestClient = context.client
        agent_base = _AGENT_BASE.format(organization_id=context.organization.id, agent_id=context.agent.id)
        source_id = context.skill.id

        with when("the owner forks a Platform Skill into the Agent scope"):
            fork = client.post(f"{agent_base}/{source_id}/fork", headers=_auth(context))
            fork_id = fork.json()["id"]
            published = client.post(f"{agent_base}/{fork_id}/draft/publish", headers=_auth(context))

        with then("the fork is Agent-private and tracks its source version"):
            assert_that(fork.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(fork.json()["scope"], equal_to("agent"))
            assert_that(published.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(published.json()["source_skill_id"], equal_to(str(source_id)))
            assert_that(published.json()["source_skill_version"], equal_to(1))

        from api.domains.skills.repository import SkillRepository

        repository: SkillRepository = context.injector.get(SkillRepository)
        repository.publish_version(source_id, [("SKILL.md", "# Platform source v2")])

        with when("the owner applies the newer direct-source version"):
            updated = client.post(f"{agent_base}/{fork_id}/source-update", headers=_auth(context))

        with then("the Agent fork publishes the selected source snapshot"):
            assert_that(updated.status_code, equal_to(status.HTTP_200_OK))
            assert_that(updated.json()["version"], equal_to(2))
            assert_that(updated.json()["source_skill_version"], equal_to(2))
            assert_that(updated.json()["files"], equal_to(_files(content="# Platform source v2")))


def test_member_without_agent_access_cannot_create_private_skill():
    with given([*_GIVEN, there_is_an_agent(), _there_is_a_member_actor()]) as context:
        agent_base = _AGENT_BASE.format(organization_id=context.organization.id, agent_id=context.agent.id)
        response = context.client.post(
            agent_base,
            json={"name": "Private Skill", "files": [{"path": "SKILL.md", "content": "# Private"}]},
            headers=_auth(context),
        )
        # Agent visibility is intentionally fail-closed to avoid leaking an
        # inaccessible Agent's existence.
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_member_cannot_fork_builtin_skill():
    with given(
        [*_GIVEN, there_is_a_skill(name="Built-in Tool", global_skill=True), _there_is_a_member_actor()]
    ) as context:
        with when("a Member tries to fork a built-in skill"):
            response = context.client.post(f"{_BASE}/{context.skill.id}/fork", headers=_auth(context))

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_start_skill_draft():
    with given([*_GIVEN, there_is_a_skill(name="Member Cannot Draft"), _there_is_a_member_actor()]) as context:
        response = context.client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_read_skill_draft():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Member Cannot Read Draft"),
            _there_is_a_skill_draft(),
            _there_is_a_member_actor(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("a member fetches the draft"):
            response = client.get(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        with then("it returns 403"):
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


def test_update_skill_draft_preserves_omitted_metadata_and_publishes_it():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Metadata Skill", required_providers=[SecretProvider.GITHUB]),
            _set_skill_description("Keep this description"),
        ]
    ) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        response = client.patch(
            f"{_BASE}/{context.skill.id}/draft",
            json={"files": _files(content="# Metadata")},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["description"], equal_to("Keep this description"))
        assert_that(response.json()["required_providers"], equal_to(["github"]))

        published = client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))
        assert_that(published.status_code, equal_to(status.HTTP_201_CREATED))
        skill = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context)).json()
        assert_that(skill["description"], equal_to("Keep this description"))
        assert_that(skill["required_providers"], equal_to(["github"]))


def test_update_skill_draft_explicit_null_clears_metadata_before_publish():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Clearable Metadata", required_providers=[SecretProvider.GITHUB]),
            _set_skill_description("Clear this description"),
        ]
    ) as context:
        client: TestClient = context.client
        client.post(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        response = client.patch(
            f"{_BASE}/{context.skill.id}/draft",
            json={"files": _files(content="# Cleared"), "description": None, "required_providers": None},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["description"], equal_to(None))
        assert_that(response.json()["required_providers"], equal_to([]))

        published = client.post(f"{_BASE}/{context.skill.id}/draft/publish", headers=_auth(context))
        assert_that(published.status_code, equal_to(status.HTTP_201_CREATED))
        skill = client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context)).json()
        assert_that(skill["description"], equal_to(None))
        assert_that(skill["required_providers"], equal_to([]))


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


def test_get_builtin_skill_draft_returns_403():
    with given([*_GIVEN, there_is_a_skill(name="Built-in Draft", global_skill=True)]) as context:
        response = context.client.get(f"{_BASE}/{context.skill.id}/draft", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


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


def test_member_cannot_delete_skill_version():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill"), _there_is_a_member_actor()]) as context:
        response = context.client.delete(f"{_BASE}/{context.skill.id}/versions/1", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_skill_version_requires_auth():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        response = context.client.delete(f"{_BASE}/{context.skill.id}/versions/1")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_delete_skill_version_not_found_returns_404():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I delete a version that was never published"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/99", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_delete_skill_version_for_aai_cli_skill_returns_403():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill", global_skill=True)]) as context:
        client: TestClient = context.client

        with when("I try to delete a built-in skill's version"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/1", headers=_auth(context))

        with then("it returns 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_historical_skill_version_returns_204():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")

        with when("I delete the historical version 1"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/1", headers=_auth(context))

        with then("version 1 is gone and version 2 remains current"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            versions = client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context)).json()
            assert_that([v["version"] for v in versions], equal_to([2]))
            assert_that(
                client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context)).json()["version"], equal_to(2)
            )


def test_delete_latest_skill_version_when_unassigned_returns_204():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")

        with when("I delete the latest version 2 while no agent uses the skill"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/2", headers=_auth(context))

        with then("it is removed and version 1 becomes current"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            versions = client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context)).json()
            assert_that([v["version"] for v in versions], equal_to([1]))
            assert_that(
                client.get(f"{_BASE}/{context.skill.id}", headers=_auth(context)).json()["version"], equal_to(1)
            )


def test_delete_skill_version_pinned_by_agent_returns_409():
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Versioned Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        client: TestClient = context.client
        _publish_new_version(client, context, "# v2")
        from api.domains.agents.repository import AgentRepository

        agent_repo: AgentRepository = context.injector.get(AgentRepository)
        agent_repo.re_pin_skill(context.agent.id, context.skill.id, 2)

        with when("I try to delete a version the agent is pinned to"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/2", headers=_auth(context))

        with then("it returns 409 and the version stays"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("pinned by an agent"))
            versions = client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context)).json()
            assert_that([v["version"] for v in versions], equal_to([2, 1]))


def test_delete_skill_version_when_only_version_returns_409():
    with given([*_GIVEN, there_is_a_skill(name="Versioned Skill")]) as context:
        client: TestClient = context.client

        with when("I try to delete a skill's only version"):
            response = client.delete(f"{_BASE}/{context.skill.id}/versions/1", headers=_auth(context))

        with then("it returns 409 and the version stays"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(response.json()["detail"], contains_string("only version"))
            assert_that(
                client.get(f"{_BASE}/{context.skill.id}/versions", headers=_auth(context)).json(),
                has_items(has_item("version")),
            )


def test_composite_fk_blocks_db_level_delete_of_pinned_version():
    """The composite FK on agent_skill(skill_id, pinned_version) is the DB-level
    safety net for the concurrent delete/pin race — bypassing the service's
    application-level check, a raw DELETE on a pinned skill_version must fail."""
    with given(
        [
            *_GIVEN,
            there_is_an_agent(),
            there_is_a_skill(name="Pinned Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        from sqlalchemy.exc import IntegrityError
        from sqlmodel import Session, col, delete, select

        from api.domains.skills.models import SkillVersion
        from api.domains.skills.repository import SkillRepository

        repo: SkillRepository = context.injector.get(SkillRepository)

        with when("I try to delete the pinned version at the DB level"):
            with Session(repo.delegate.engine) as session:
                version_row = session.exec(
                    select(SkillVersion).where(col(SkillVersion.skill_id) == context.skill.id)
                ).first()
                assert version_row is not None

                with then("the composite FK raises IntegrityError"):
                    try:
                        session.exec(  # type: ignore[call-overload]
                            delete(SkillVersion).where(col(SkillVersion.id) == version_row.id)
                        )
                        session.commit()
                        raise AssertionError("Expected IntegrityError")
                    except IntegrityError:
                        session.rollback()
