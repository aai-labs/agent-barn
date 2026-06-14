import io
import json
import zipfile

from api.domains.agents.aai_cli_skills import (
    AAI_CLI_PROVIDER_SKILLS,
    build_skills_manifest_from_zips,
    build_zip,
)

_EXPECTED_PROVIDER_NAMES = {
    "aai-cli-jira",
    "aai-cli-confluence",
    "aai-cli-github",
    "aai-cli-bitbucket",
}


def test_aai_cli_provider_skills_has_expected_entries():
    names = {s["name"] for s in AAI_CLI_PROVIDER_SKILLS}
    assert names == _EXPECTED_PROVIDER_NAMES


def test_each_provider_skill_has_required_providers():
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        assert skill_def["required_providers"], f"No required_providers for {skill_def['name']}"


def test_each_provider_skill_has_non_empty_files():
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        assert skill_def["files"], f"No files for {skill_def['name']}"
        for f in skill_def["files"]:
            assert f["skill_content"].strip(), (
                f"Empty content in {f['skill_file_path']} for {skill_def['name']}"
            )


def test_build_zip_produces_valid_zip():
    skill_def = AAI_CLI_PROVIDER_SKILLS[0]
    zip_bytes = build_zip(skill_def["files"])
    buf = io.BytesIO(zip_bytes)
    with zipfile.ZipFile(buf, "r") as zf:
        names = set(zf.namelist())
    expected = {f["skill_file_path"] for f in skill_def["files"]}
    assert names == expected


def test_build_skills_manifest_from_zips_returns_sorted_path_content():
    # Build fake (AgentSkill, Skill) tuples using simple namespaces.
    from types import SimpleNamespace

    entries = []
    for skill_def in AAI_CLI_PROVIDER_SKILLS:
        zip_content = build_zip(skill_def["files"])
        fake_skill = SimpleNamespace(zip_content=zip_content)
        fake_agent_skill = SimpleNamespace()
        entries.append((fake_agent_skill, fake_skill))

    manifest_str = build_skills_manifest_from_zips(entries)
    manifest = json.loads(manifest_str)

    paths = [m["path"] for m in manifest]
    assert paths == sorted(paths), "Manifest entries should be sorted by path"

    for entry in manifest:
        assert set(entry.keys()) == {"path", "content"}, (
            "Each manifest entry must have only 'path' and 'content'"
        )

    expected = {
        f["skill_file_path"]: f["skill_content"]
        for skill_def in AAI_CLI_PROVIDER_SKILLS
        for f in skill_def["files"]
    }
    for entry in manifest:
        assert entry["content"] == expected[entry["path"]], (
            f"Content mismatch for {entry['path']}"
        )