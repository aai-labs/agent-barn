import json
import uuid

from api.domains.agents.aai_cli_skills import (
    AAI_CLI_SKILLS,
    build_skills_manifest,
    load_aai_cli_skills,
)
from api.domains.agents.models import SkillSource

_EXPECTED_PATHS = {
    # index
    "aai-cli/aai-cli_skill.md",
    # jira (6)
    "aai-cli/jira_skill/jira_skill.md",
    "aai-cli/jira_skill/jira_board_skill/jira_board_skill.md",
    "aai-cli/jira_skill/jira_issue_skill/jira_issue_skill.md",
    "aai-cli/jira_skill/jira_project_skill/jira_project_skill.md",
    "aai-cli/jira_skill/jira_sprint_skill/jira_sprint_skill.md",
    "aai-cli/jira_skill/jira_user_skill/jira_user_skill.md",
    # confluence (5)
    "aai-cli/confluence_skill/confluence_skill.md",
    "aai-cli/confluence_skill/confluence_page_skill/confluence_page_skill.md",
    "aai-cli/confluence_skill/confluence_page_attachment_skill/confluence_page_attachment_skill.md",
    "aai-cli/confluence_skill/confluence_page_comment_skill/confluence_page_comment_skill.md",
    "aai-cli/confluence_skill/confluence_space_skill/confluence_space_skill.md",
    # github (7)
    "aai-cli/github_skill/github_skill.md",
    "aai-cli/github_skill/github_repo_skill/github_repo_skill.md",
    "aai-cli/github_skill/github_issue_skill/github_issue_skill.md",
    "aai-cli/github_skill/github_branch_skill/github_branch_skill.md",
    "aai-cli/github_skill/github_pr_skill/github_pr_skill.md",
    "aai-cli/github_skill/github_source_skill/github_source_skill.md",
    "aai-cli/github_skill/github_actions_skill/github_actions_skill.md",
    # bitbucket (7)
    "aai-cli/bitbucket_skill/bitbucket_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_repo_skill/bitbucket_repo_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_branch_skill/bitbucket_branch_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_commit_skill/bitbucket_commit_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_pr_skill/bitbucket_pr_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_source_skill/bitbucket_source_skill.md",
    "aai-cli/bitbucket_skill/bitbucket_pipeline_skill/bitbucket_pipeline_skill.md",
}


def test_data_module_has_expected_entries():
    paths = {e["skill_file_path"] for e in AAI_CLI_SKILLS}
    assert paths == _EXPECTED_PATHS
    for e in AAI_CLI_SKILLS:
        assert e["skill_content"].strip(), e["skill_file_path"]  # non-empty
        assert e["skill_name"] == "aai-cli"


def test_load_aai_cli_skills_builds_rows_for_agent():
    agent_id = uuid.uuid4()
    rows = load_aai_cli_skills(agent_id)
    assert len(rows) == len(_EXPECTED_PATHS)
    assert all(r.agent_id == agent_id for r in rows)
    assert all(r.source == SkillSource.AAI_CLI for r in rows)
    assert {r.skill_file_path for r in rows} == _EXPECTED_PATHS


def test_index_links_all_providers_content_preserved():
    by_path = {e["skill_file_path"]: e["skill_content"] for e in AAI_CLI_SKILLS}
    index = by_path["aai-cli/aai-cli_skill.md"]
    # index links to all 4 providers
    assert "./jira_skill/jira_skill.md" in index
    assert "./confluence_skill/confluence_skill.md" in index
    assert "./github_skill/github_skill.md" in index
    assert "./bitbucket_skill/bitbucket_skill.md" in index
    # verbatim content headings from source files preserved
    assert "# aai-cli Jira Skill" in by_path["aai-cli/jira_skill/jira_skill.md"]
    assert (
        "# aai-cli Confluence Skill"
        in by_path["aai-cli/confluence_skill/confluence_skill.md"]
    )
    assert "# aai-cli GitHub Skill" in by_path["aai-cli/github_skill/github_skill.md"]
    assert (
        "# aai-cli Bitbucket Skill"
        in by_path["aai-cli/bitbucket_skill/bitbucket_skill.md"]
    )


def test_required_flag_edit_applied_no_config_flags():
    by_path = {e["skill_file_path"]: e["skill_content"] for e in AAI_CLI_SKILLS}
    root_files = [
        "aai-cli/jira_skill/jira_skill.md",
        "aai-cli/confluence_skill/confluence_skill.md",
        "aai-cli/github_skill/github_skill.md",
        "aai-cli/bitbucket_skill/bitbucket_skill.md",
    ]
    for path in root_files:
        content = by_path[path]
        assert "Required flag" in content, f"Required flag section missing: {path}"
        assert "--config" not in content, f"--config still present: {path}"
        assert "--secrets-file" not in content, f"--secrets-file still present: {path}"
        assert "--key-file" not in content, f"--key-file still present: {path}"


def test_build_skills_manifest_is_sorted_path_content_only():
    rows = load_aai_cli_skills(uuid.uuid4())
    manifest = json.loads(build_skills_manifest(rows))
    assert [m["path"] for m in manifest] == sorted(_EXPECTED_PATHS)
    assert all(
        set(m.keys()) == {"path", "content"} for m in manifest
    )  # no source leaked
    by_path = {e["skill_file_path"]: e["skill_content"] for e in AAI_CLI_SKILLS}
    assert all(m["content"] == by_path[m["path"]] for m in manifest)
