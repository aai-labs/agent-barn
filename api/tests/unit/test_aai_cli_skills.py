import json
from types import SimpleNamespace
from uuid import uuid7

from api.domains.agents.aai_cli_skills import (
    AAI_CLI_PROVIDER_SKILLS,
    AAI_CLI_ROOT_DIR,
    build_skills_manifest,
    root_relative_files,
)

_EXPECTED_PROVIDER_NAMES = {
    "Jira",
    "Confluence",
    "GitHub",
    "Bitbucket",
    "Google Drive",
    "Excel",
    "HubSpot",
    "OpenPanel",
    "Zoho Mail",
    "Slack",
    "Pipedrive",
    "PostHog",
}

# Excel intentionally needs no credential. The other four entries currently have
# no Agent Farm SecretProvider model, so they remain explicit-only until that wiring exists.
_CREDENTIAL_FREE_SKILLS = {"Excel"}
_UNMANAGED_BUNDLED_SKILLS = {"Google Drive", "HubSpot", "OpenPanel", "PostHog"}


def test_aai_cli_provider_skills_has_expected_entries():
    names = {s["name"] for s in AAI_CLI_PROVIDER_SKILLS}
    assert names == _EXPECTED_PROVIDER_NAMES


def test_each_provider_skill_has_required_providers():
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        if skill_def["name"] in _CREDENTIAL_FREE_SKILLS | _UNMANAGED_BUNDLED_SKILLS:
            continue
        assert skill_def["required_providers"], f"No required_providers for {skill_def['name']}"


def test_credential_free_skills_declare_no_providers():
    """The empty list is the whole point — it keeps the skill selectable while stopping
    the provider auto-attach path from attaching it to every agent."""
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        if skill_def["name"] in _CREDENTIAL_FREE_SKILLS:
            assert skill_def["required_providers"] == []


def test_each_bundled_skill_has_exactly_one_root_skill_md():
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        root_files = [
            file["skill_file_path"]
            for file in skill_def["files"]
            if file["skill_file_path"] == f"{skill_def['bundle_dir']}/SKILL.md"
        ]
        assert root_files == [f"{skill_def['bundle_dir']}/SKILL.md"]
        assert all(file["skill_file_path"].startswith(f"{skill_def['bundle_dir']}/") for file in skill_def["files"])


def test_each_provider_skill_has_non_empty_files():
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        assert skill_def["files"], f"No files for {skill_def['name']}"
        for f in skill_def["files"]:
            assert f["skill_content"].strip(), f"Empty content in {f['skill_file_path']} for {skill_def['name']}"


def test_each_provider_skill_entry_path_is_root_relative():
    """entry_path addresses a file inside the skill, so it must not repeat root_dir."""
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        entry = skill_def["entry_path"]
        assert entry == skill_def["files"][0]["skill_file_path"].removeprefix(f"{skill_def['bundle_dir']}/")
        assert not entry.startswith(f"{AAI_CLI_ROOT_DIR}/"), f"{skill_def['name']} entry_path keeps its root prefix"
        declared = {f["skill_file_path"] for f in skill_def["files"]}
        assert f"{skill_def['bundle_dir']}/{entry}" in declared, f"{skill_def['name']} entry_path names no shipped file"


def test_root_relative_files_strips_the_shared_mount_directory():
    skill_def = AAI_CLI_PROVIDER_SKILLS[0]
    files = root_relative_files(
        skill_def["files"],
        entry_path=skill_def["entry_path"],
        root_dir="jira",
    )
    assert [path for path, _ in files] == ["SKILL.md", "references/command-reference.md"]


def _fake_skill(name: str, root_dir: str):
    return SimpleNamespace(id=uuid7(), name=name, root_dir=root_dir)


def _fake_files(paths_to_content: dict[str, str]):
    return [SimpleNamespace(path=path, content=content) for path, content in paths_to_content.items()]


def test_build_skills_manifest_returns_sorted_path_content():
    skills = []
    files_by_skill_id = {}
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        root_dir = skill_def["bundle_dir"]
        skill = _fake_skill(skill_def["name"], root_dir)
        skills.append(skill)
        files_by_skill_id[skill.id] = _fake_files(
            dict(
                root_relative_files(
                    skill_def["files"],
                    entry_path=skill_def["entry_path"],
                    root_dir=root_dir,
                )
            )
        )

    manifest_str, collisions = build_skills_manifest(skills, files_by_skill_id)
    manifest = json.loads(manifest_str)

    assert collisions == []
    paths = [m["path"] for m in manifest]
    assert paths == sorted(paths), "Manifest entries should be sorted by path"

    for entry in manifest:
        assert set(entry.keys()) == {"path", "content"}, "Each manifest entry must have only 'path' and 'content'"

    expected = {
        f"{skill_def['bundle_dir']}/{path}": content
        for skill_def in AAI_CLI_PROVIDER_SKILLS
        for path, content in root_relative_files(
            skill_def["files"],
            entry_path=skill_def["entry_path"],
            root_dir=skill_def["bundle_dir"],
        )
    }
    for entry in manifest:
        assert entry["content"] == expected[entry["path"]], f"Content mismatch for {entry['path']}"


def test_build_skills_manifest_reports_colliding_paths():
    """Two skills sharing a root_dir can claim one path; the loser must be reported
    rather than silently overwriting the winner."""
    first = _fake_skill("Alpha", AAI_CLI_ROOT_DIR)
    second = _fake_skill("Beta", AAI_CLI_ROOT_DIR)
    files_by_skill_id = {
        first.id: _fake_files({"shared.md": "from alpha"}),
        second.id: _fake_files({"shared.md": "from beta", "own.md": "kept"}),
    }

    manifest_str, collisions = build_skills_manifest([second, first], files_by_skill_id)
    manifest = {entry["path"]: entry["content"] for entry in json.loads(manifest_str)}

    # Order is by skill name, not call order, so the winner is deterministic.
    assert manifest[f"{AAI_CLI_ROOT_DIR}/shared.md"] == "from alpha"
    assert manifest[f"{AAI_CLI_ROOT_DIR}/own.md"] == "kept"
    assert len(collisions) == 1
    assert "shared.md" in collisions[0]
    assert "Alpha" in collisions[0] and "Beta" in collisions[0]


def test_build_skills_manifest_allows_same_path_under_different_roots():
    alpha = _fake_skill("Alpha", "alpha")
    beta = _fake_skill("Beta", "beta")
    files_by_skill_id = {
        alpha.id: _fake_files({"SKILL.md": "a"}),
        beta.id: _fake_files({"SKILL.md": "b"}),
    }

    manifest_str, collisions = build_skills_manifest([alpha, beta], files_by_skill_id)
    manifest = {entry["path"]: entry["content"] for entry in json.loads(manifest_str)}

    assert collisions == []
    assert manifest == {"alpha/SKILL.md": "a", "beta/SKILL.md": "b"}
