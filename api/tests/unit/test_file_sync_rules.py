import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from hamcrest import assert_that, calling, equal_to, is_in, none, raises

from api.domains.agents.builders.openclaw import build_config_map
from api.domains.agents.restore_point_job import HERMES_EXCLUDED, OPENCLAW_EXCLUDED
from api.domains.file_sync.rules import (
    MAX_FILE_BYTES,
    MAX_PATH_CHARS,
    NameProblem,
    SyncCategory,
    classify,
    name_problem,
    path_too_long,
    rules_manifest,
)

_HERMES = "hermes"
_OPENCLAW = "openclaw"

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "domains" / "agents"
_HERMES_START = _AGENTS_DIR / "scripts" / "hermes" / "start.sh"
_HERMES_WORKSPACE_COPY_LOOP = re.compile(r"^for f in (?P<files>[^;]+); do$", re.MULTILINE)


def _hermes_workspace_copies() -> set[str]:
    match = _HERMES_WORKSPACE_COPY_LOOP.search(_HERMES_START.read_text(encoding="utf-8"))
    assert match is not None
    return {f"workspace/{name}" for name in match.group("files").split()}


def _openclaw_config_map_markdown() -> set[str]:
    config_map = build_config_map(
        agent_id=uuid4(),
        org_id=uuid4(),
        namespace="agent-farm",
        soul_md="x",
        identity_md="x",
        user_md="x",
        tools_md="x",
        agents_md="x",
        boot_md="x",
        bootstrap_md="x",
        heartbeat_md="x",
        openclaw_config_overlay={"agents": {}},
        skills_json="[]",
    )
    return {key for key in config_map.data if key.endswith(".md")}


def _machinery(excluded: tuple[str, ...]) -> list[str]:
    return [path for path in excluded if not path.startswith("workspace/") and path != "SOUL.md"]


@pytest.mark.parametrize(
    ("runtime", "path"),
    [(_HERMES, path) for path in _machinery(HERMES_EXCLUDED)]
    + [(_OPENCLAW, path) for path in _machinery(OPENCLAW_EXCLUDED)],
)
def test_credentials_and_runtime_machinery_never_sync(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.NEVER))
    assert_that(classify(runtime, f"{path}/nested/file.json"), equal_to(SyncCategory.NEVER))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [(_HERMES, path) for path in HERMES_EXCLUDED] + [(_OPENCLAW, path) for path in OPENCLAW_EXCLUDED],
)
def test_nothing_a_restore_point_excludes_is_ever_writable_from_the_provider(runtime, path):
    allowed = (SyncCategory.NEVER, SyncCategory.CONFIG, SyncCategory.SKILLS)

    assert_that(classify(runtime, path), is_in(allowed))
    assert_that(classify(runtime, f"{path}/nested/file.md"), is_in(allowed))


@pytest.mark.parametrize("path", sorted(_hermes_workspace_copies() | {"SOUL.md"}))
def test_hermes_files_rebuilt_from_the_template_are_config(path):
    assert_that(classify(_HERMES, path), equal_to(SyncCategory.CONFIG))


@pytest.mark.parametrize("name", sorted(_openclaw_config_map_markdown() - {"USER.md"}))
def test_openclaw_files_rebuilt_from_the_template_are_config(name):
    assert_that(classify(_OPENCLAW, f"workspace/{name}"), equal_to(SyncCategory.CONFIG))


@pytest.mark.parametrize("runtime", [_HERMES, _OPENCLAW])
def test_skills_are_mirrored_read_only(runtime):
    assert_that(classify(runtime, "workspace/skills/jira/SKILL.md"), equal_to(SyncCategory.SKILLS))
    assert_that(classify(runtime, "workspace/skills/jira/scripts/run.py"), equal_to(SyncCategory.SKILLS))


@pytest.mark.parametrize("runtime", [_HERMES, _OPENCLAW])
def test_a_sibling_sharing_the_skills_prefix_is_ordinary_work(runtime):
    assert_that(classify(runtime, "workspace/skillsX/notes.md"), equal_to(SyncCategory.WORK))
    assert_that(classify(runtime, "workspace/skills.md"), equal_to(SyncCategory.WORK))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [
        (_HERMES, "memories/USER.md"),
        (_HERMES, "memories/MEMORY.md"),
        (_OPENCLAW, "workspace/USER.md"),
        (_OPENCLAW, "workspace/MEMORY.md"),
    ],
)
def test_agent_owned_memory_files_are_memory(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.MEMORY))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [
        (_HERMES, "workspace/notes.md"),
        (_HERMES, "workspace/memory/2026-10-21.md"),
        (_HERMES, "workspace/reports/q3/summary.docx"),
        (_OPENCLAW, "workspace/notes.md"),
        (_OPENCLAW, "workspace/memory/2026-10-21.md"),
        (_OPENCLAW, "workspace/DREAMS.md"),
    ],
)
def test_other_workspace_files_are_work(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.WORK))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [
        (_HERMES, "memories/other.md"),
        (_HERMES, "sessions/abc.json"),
        (_HERMES, "state.db"),
        (_HERMES, "logs/gateway.log"),
        (_HERMES, "USER.md"),
        (_OPENCLAW, "npm/projects/openclaw-plugin/package.json"),
        (_OPENCLAW, "agents/main/sessions/abc.jsonl"),
        (_OPENCLAW, "memories/MEMORY.md"),
        (_HERMES, "workspace"),
        (_OPENCLAW, "workspace"),
    ],
)
def test_anything_outside_the_allowlist_never_syncs(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.NEVER))


@pytest.mark.parametrize(
    "path",
    [
        "workspace/.git/config",
        "workspace/app/node_modules/left-pad/index.js",
        "workspace/pkg/__pycache__/mod.cpython-312.pyc",
        "workspace/skills/jira/__pycache__/run.cpython-312.pyc",
    ],
)
def test_tool_and_dependency_directories_never_sync(path):
    assert_that(classify(_HERMES, path), equal_to(SyncCategory.NEVER))
    assert_that(classify(_OPENCLAW, path), equal_to(SyncCategory.NEVER))


@pytest.mark.parametrize(
    "path",
    [
        "workspace/.env",
        "workspace/.netrc",
        "workspace/project/.env",
        "workspace/.gitignore",
        "workspace/.ssh/id_rsa",
        "workspace/.venv/lib/site.py",
        "workspace/venv/lib/site.py",
        "workspace/project/venv/bin/python",
        "workspace/.cache/pip/wheel.whl",
        "workspace/.cursor/settings.json",
        "workspace/skills/jira/.env",
    ],
)
def test_hidden_files_and_virtualenvs_never_sync(path):
    assert_that(classify(_HERMES, path), equal_to(SyncCategory.NEVER))
    assert_that(classify(_OPENCLAW, path), equal_to(SyncCategory.NEVER))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [
        (_HERMES, "SOUL.md"),
        (_HERMES, "soul.md"),
        (_HERMES, "workspace/AGENTS.md"),
        (_HERMES, "workspace/agents.md"),
        (_HERMES, "workspace/Agents.md"),
        (_HERMES, "workspace/AGENTS.override.md"),
        (_HERMES, "workspace/agents.override.md"),
        (_HERMES, "workspace/HERMES.md"),
        (_HERMES, "workspace/.hermes.md"),
        (_HERMES, "workspace/CLAUDE.md"),
        (_HERMES, "workspace/claude.md"),
        (_HERMES, "workspace/.cursorrules"),
        (_HERMES, "workspace/.cursor/rules/style.mdc"),
        (_HERMES, "workspace/identity.md"),
        (_OPENCLAW, "workspace/agents.md"),
        (_OPENCLAW, "workspace/soul.md"),
        (_OPENCLAW, "workspace/Bootstrap.md"),
        (_OPENCLAW, "workspace/CLAUDE.md"),
    ],
)
def test_every_name_the_runtime_reads_as_instructions_is_locked_whatever_its_case(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.CONFIG))


@pytest.mark.parametrize(
    ("runtime", "path"),
    [
        (_HERMES, "memories/user.md"),
        (_HERMES, "memories/Memory.md"),
        (_OPENCLAW, "workspace/user.md"),
        (_OPENCLAW, "workspace/memory.md"),
    ],
)
def test_memory_files_match_whatever_their_case(runtime, path):
    assert_that(classify(runtime, path), equal_to(SyncCategory.MEMORY))


@pytest.mark.parametrize("runtime", [_HERMES, _OPENCLAW])
def test_skills_match_whatever_their_case(runtime):
    assert_that(classify(runtime, "workspace/Skills/jira/SKILL.md"), equal_to(SyncCategory.SKILLS))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/workspace/notes.md",
        "workspace/../.env",
        "workspace/./notes.md",
        "workspace//notes.md",
        "workspace/notes.md/",
        "workspace\\notes.md",
        "workspace/no\x00tes.md",
        "workspace/no\ntes.md",
        "_Not synced/notes.md",
    ],
)
def test_malformed_or_reserved_paths_never_sync(path):
    assert_that(classify(_HERMES, path), equal_to(SyncCategory.NEVER))


def test_an_unknown_runtime_is_refused():
    assert_that(calling(classify).with_args("other", "workspace/notes.md"), raises(ValueError))
    assert_that(calling(rules_manifest).with_args("other"), raises(ValueError))


@pytest.mark.parametrize(
    ("path", "problem"),
    [
        ("workspace/a:b.md", NameProblem.FORBIDDEN_CHARACTER),
        ('workspace/a"b.md', NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a*b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a<b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a>b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a?b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a|b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/a\\b.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/bad:dir/notes.md", NameProblem.FORBIDDEN_CHARACTER),
        ("workspace/ leading.md", NameProblem.LEADING_SPACE),
        ("workspace/trailing.", NameProblem.TRAILING_DOT_OR_SPACE),
        ("workspace/trailing ", NameProblem.TRAILING_DOT_OR_SPACE),
        ("workspace/dir./notes.md", NameProblem.TRAILING_DOT_OR_SPACE),
        ("workspace/CON", NameProblem.RESERVED_NAME),
        ("workspace/aux", NameProblem.RESERVED_NAME),
        ("workspace/CON.txt", NameProblem.RESERVED_NAME),
        ("workspace/com1.log", NameProblem.RESERVED_NAME),
        ("workspace/_vti_x", NameProblem.RESERVED_PREFIX),
    ],
)
def test_names_the_provider_refuses_are_reported(path, problem):
    assert_that(name_problem(path), equal_to(problem))


@pytest.mark.parametrize(
    "path",
    [
        "workspace/a#b.md",
        "workspace/a%b.md",
        "workspace/.lock",
        "workspace/~$lock.docx",
        "workspace/desktop.ini",
        "workspace/forms",
        "workspace/console.md",
        "workspace/CONFIG.md",
        f"workspace/{'n' * 256}",
    ],
)
def test_names_the_provider_accepts_have_no_problem(path):
    assert_that(name_problem(path), none())


def test_the_provider_path_limit_counts_the_agent_folder_and_the_relative_path():
    folder = "/sites/AgentBarnTest/Shared Documents/Agent Barn/Sales Bot"
    fits = "workspace/" + "n" * (MAX_PATH_CHARS - len(folder) - 1 - len("workspace/"))

    assert_that(len(f"{folder}/{fits}"), equal_to(MAX_PATH_CHARS))
    assert_that(path_too_long(folder, fits), equal_to(False))
    assert_that(path_too_long(folder, fits + "n"), equal_to(True))


@pytest.mark.parametrize(("runtime", "root"), [(_HERMES, "/opt/data"), (_OPENCLAW, "/home/node/.openclaw")])
def test_the_pod_manifest_carries_the_same_rules_as_json(runtime, root):
    manifest = json.loads(json.dumps(rules_manifest(runtime)))

    assert_that(manifest["root"], equal_to(root))
    assert_that(manifest["max_file_bytes"], equal_to(MAX_FILE_BYTES))
    assert_that(manifest["max_file_bytes"], equal_to(100 * 1024 * 1024))
    assert_that(sorted(manifest["skip_dir_names"]), equal_to([".git", "__pycache__", "node_modules", "venv"]))
    for path in manifest["config"]:
        assert_that(classify(runtime, path), equal_to(SyncCategory.CONFIG))
    for path in manifest["memory"]:
        assert_that(classify(runtime, path), equal_to(SyncCategory.MEMORY))
    assert_that(classify(runtime, f"{manifest['skills']}/a/SKILL.md"), equal_to(SyncCategory.SKILLS))
    assert_that(classify(runtime, f"{manifest['workspace']}/notes.md"), equal_to(SyncCategory.WORK))
