"""Exercise Agent Barn Skill materialization against a real Hermes image."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_item, is_

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.tests.core.givenpy import LambdaWith, given, then, when

_AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
_SKILL_NAME = "test-required-skill"
_SKILL_SENTINEL = "required-skill-sentinel"
_RESULT_PREFIX = "HERMES_SKILL_CONTRACT="

_SKILL_INPUT = textwrap.dedent(
    f"""\
    ---
    name: {_SKILL_NAME}
    description: Verifies assigned Skill discovery.
    ---

    # Required Skill

    {_SKILL_SENTINEL}
    """
)


@dataclass(frozen=True)
class SkillInput:
    slug: str
    content: str


@dataclass(frozen=True)
class HermesRun:
    exit_code: int
    stdout: str
    stderr: str
    observation_received: bool
    workspace_file_exists: bool
    reported_file_exists: bool
    listed_skills: list[str]
    skill_loaded: bool
    skill_content: str
    skill_error: str


def image_is_built(image: str):
    def step(context) -> None:
        execute(["docker", "image", "inspect", image])
        context.image = image

    return step


@pytest.fixture
def hermes_image() -> str:
    image = os.environ.get("HERMES_TEST_IMAGE")
    if not image:
        pytest.fail("HERMES_TEST_IMAGE must name an already-built Hermes image")
    return image


def empty_agent_workspace_is_present(root: Path):
    def step(context) -> LambdaWith:
        context.config_dir = root / "config"
        context.workspace_dir = root / "workspace"
        context.command_dir = root / "commands"

        context.config_dir.mkdir()
        context.workspace_dir.mkdir()
        context.command_dir.mkdir()

        root.chmod(0o755)
        context.workspace_dir.chmod(0o777)

        return LambdaWith(
            lambda: None,
            lambda: make_workspace_removable(context),
        )

    return step


def skill_is_present(input_txt: str, *, slug: str = _SKILL_NAME):
    def step(context) -> None:
        skill = SkillInput(slug=slug, content=input_txt)
        context.skills = [*getattr(context, "skills", []), skill]

    return step


def hermes_runtime_is_configured():
    def step(context) -> None:
        config_map = build_hermes_config_map(
            _AGENT_ID,
            _ORG_ID,
            "agent-farm",
            "Test soul.",
            "Test identity.",
            "Test user.",
            "Test tools.",
            "Test agents.",
            "Test boot.",
            "Test heartbeat.",
            build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000"),
            skills_json=skills_manifest(context.skills),
        )

        for name, content in config_map.data.items():
            write_file(context.config_dir / name, content)

    return step


def test_assigned_workspace_skill_should_be_discoverable_and_loadable_by_hermes(
    hermes_image: str,
    tmp_path: Path,
) -> None:
    with given(
        [
            image_is_built(hermes_image),
            empty_agent_workspace_is_present(tmp_path),
            skill_is_present(_SKILL_INPUT),
            hermes_runtime_is_configured(),
        ]
    ) as context:
        with when("the Hermes agent starts"):
            result = start_hermes_agent(context)

        with then("the generated runtime should start successfully"):
            assert_that(result.exit_code, equal_to(0), result.stderr)
            assert_that(result.observation_received, is_(True), result.stdout + result.stderr)

        with then("Agent Barn should materialize the assigned Skill"):
            assert_that(result.workspace_file_exists, is_(True))
            assert_that(result.reported_file_exists, is_(True))

        with then("Hermes should list the assigned Skill"):
            assert_that(result.listed_skills, has_item(_SKILL_NAME))

        with then("Hermes should load the assigned Skill"):
            assert_that(result.skill_loaded, is_(True), result.skill_error)
            assert_that(result.skill_content, contains_string(_SKILL_SENTINEL))


def start_hermes_agent(context) -> HermesRun:
    install_skill_discovery_probe(context.command_dir)
    completed = execute(hermes_start_command(context), check=False)
    observation = read_observation(completed.stdout)

    return HermesRun(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        observation_received=observation is not None,
        workspace_file_exists=bool(observation and observation.get("workspace_file_exists")),
        reported_file_exists=bool(observation and observation.get("reported_file_exists")),
        listed_skills=list(observation.get("listed_skills", [])) if observation else [],
        skill_loaded=bool(observation and observation.get("skill_loaded")),
        skill_content=str(observation.get("skill_content", "")) if observation else "",
        skill_error=str(observation.get("skill_error", "")) if observation else "",
    )


def hermes_start_command(context) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-e",
        "PATH=/contract-commands:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "-v",
        f"{context.config_dir}:/app/config:ro",
        "-v",
        f"{context.workspace_dir}:/workspace",
        "-v",
        f"{context.workspace_dir}:/opt/data/workspace",
        "-v",
        f"{context.command_dir}:/contract-commands:ro",
        "--entrypoint",
        "sh",
        context.image,
        "/app/config/start.sh",
    ]


def execute(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def make_workspace_removable(context) -> None:
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "0",
            "-v",
            f"{context.workspace_dir}:/workspace",
            "--entrypoint",
            "sh",
            context.image,
            "-c",
            "chmod -R a+rwX /workspace",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_observation(stdout: str) -> dict[str, Any] | None:
    for line in stdout.splitlines():
        if line.startswith(_RESULT_PREFIX):
            return json.loads(line.removeprefix(_RESULT_PREFIX))
    return None


def skills_manifest(skills: list[SkillInput]) -> str:
    return json.dumps([{"path": f"{skill.slug}/SKILL.md", "content": skill.content} for skill in skills])


def write_file(path: Path, content: str, *, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)


def install_skill_discovery_probe(command_dir: Path) -> None:
    write_file(command_dir / "hermes", skill_discovery_probe(), executable=True)


def skill_discovery_probe() -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import json
        import sys
        from pathlib import Path

        sys.path.insert(0, "/opt/hermes")

        from tools.skills_tool import skill_view, skills_list

        listed = json.loads(skills_list())
        loaded = json.loads(skill_view("{_SKILL_NAME}"))

        observation = {{
            "workspace_file_exists": Path(
                "/workspace/skills/{_SKILL_NAME}/SKILL.md"
            ).is_file(),
            "reported_file_exists": Path(
                "/opt/data/workspace/skills/{_SKILL_NAME}/SKILL.md"
            ).is_file(),
            "listed_skills": [
                skill["name"]
                for skill in listed.get("skills", [])
            ],
            "skill_loaded": loaded.get("success", False),
            "skill_content": loaded.get("content", ""),
            "skill_error": loaded.get("error", ""),
        }}

        print("{_RESULT_PREFIX}" + json.dumps(observation))
        """
    )
