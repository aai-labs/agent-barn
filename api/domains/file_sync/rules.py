from dataclasses import dataclass
from enum import StrEnum

from api.domains.agents.restore_point_job import RUNTIME_HERMES, RUNTIME_OPENCLAW

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PATH_CHARS = 400
NOT_SYNCED_DIR = "_Not synced"
SKIP_DIR_NAMES = frozenset({".git", "node_modules", "__pycache__", "venv"})
FORBIDDEN_CHARACTERS = frozenset(':"*<>?|\\')
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(10)} | {f"LPT{n}" for n in range(10)}
)
RESERVED_PREFIX = "_vti_"
WORKSPACE = "workspace"
SKILLS = "workspace/skills"


class SyncCategory(StrEnum):
    WORK = "work"
    MEMORY = "memory"
    CONFIG = "config"
    SKILLS = "skills"
    NEVER = "never"


class NameProblem(StrEnum):
    FORBIDDEN_CHARACTER = "forbidden_character"
    LEADING_SPACE = "leading_space"
    TRAILING_DOT_OR_SPACE = "trailing_dot_or_space"
    RESERVED_NAME = "reserved_name"
    RESERVED_PREFIX = "reserved_prefix"


@dataclass(frozen=True)
class RuntimeRules:
    root: str
    config: frozenset[str]
    memory: frozenset[str]


RUNTIME_RULES = {
    RUNTIME_HERMES: RuntimeRules(
        root="/opt/data",
        config=frozenset(
            {
                "SOUL.md",
                "workspace/IDENTITY.md",
                "workspace/AGENTS.md",
                "workspace/AGENTS.override.md",
                "workspace/HERMES.md",
                "workspace/.hermes.md",
                "workspace/CLAUDE.md",
                "workspace/.cursorrules",
                "workspace/.cursor/rules",
                "workspace/TOOLS.md",
                "workspace/BOOT.md",
                "workspace/HEARTBEAT.md",
            }
        ),
        memory=frozenset({"memories/USER.md", "memories/MEMORY.md"}),
    ),
    RUNTIME_OPENCLAW: RuntimeRules(
        root="/home/node/.openclaw",
        config=frozenset(
            {
                "workspace/SOUL.md",
                "workspace/IDENTITY.md",
                "workspace/AGENTS.md",
                "workspace/TOOLS.md",
                "workspace/BOOT.md",
                "workspace/BOOTSTRAP.md",
                "workspace/HEARTBEAT.md",
                "workspace/CLAUDE.md",
            }
        ),
        memory=frozenset({"workspace/USER.md", "workspace/MEMORY.md"}),
    ),
}


def _rules(runtime: str) -> RuntimeRules:
    try:
        return RUNTIME_RULES[runtime]
    except KeyError:
        raise ValueError(f"unknown runtime: {runtime}") from None


def _segments(rel_path: str) -> list[str] | None:
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in rel_path):
        return None
    segments = rel_path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    return segments


def _under(rel_path: str, entry: str) -> bool:
    return rel_path == entry or rel_path.startswith(f"{entry}/")


def classify(runtime: str, rel_path: str) -> SyncCategory:
    rules = _rules(runtime)
    segments = _segments(rel_path)
    if segments is None or segments[0] == NOT_SYNCED_DIR:
        return SyncCategory.NEVER
    if any(segment.lower() in SKIP_DIR_NAMES for segment in segments):
        return SyncCategory.NEVER
    folded = rel_path.lower()
    if any(folded == entry.lower() for entry in rules.memory):
        return SyncCategory.MEMORY
    if any(_under(folded, entry.lower()) for entry in rules.config):
        return SyncCategory.CONFIG
    if any(segment.startswith(".") for segment in segments):
        return SyncCategory.NEVER
    if _under(folded, SKILLS):
        return SyncCategory.SKILLS
    if rel_path.startswith(f"{WORKSPACE}/"):
        return SyncCategory.WORK
    return SyncCategory.NEVER


def name_problem(rel_path: str) -> NameProblem | None:
    for segment in rel_path.split("/"):
        if any(char in FORBIDDEN_CHARACTERS for char in segment):
            return NameProblem.FORBIDDEN_CHARACTER
        if segment.startswith(" "):
            return NameProblem.LEADING_SPACE
        if segment.endswith((".", " ")):
            return NameProblem.TRAILING_DOT_OR_SPACE
        if segment.split(".", 1)[0].upper() in RESERVED_NAMES:
            return NameProblem.RESERVED_NAME
        if segment.lower().startswith(RESERVED_PREFIX):
            return NameProblem.RESERVED_PREFIX
    return None


def path_too_long(folder_path: str, rel_path: str) -> bool:
    return len(f"{folder_path.rstrip('/')}/{rel_path}") > MAX_PATH_CHARS


def rules_manifest(runtime: str) -> dict:
    rules = _rules(runtime)
    return {
        "root": rules.root,
        "workspace": WORKSPACE,
        "skills": SKILLS,
        "config": sorted(rules.config),
        "memory": sorted(rules.memory),
        "skip_dir_names": sorted(SKIP_DIR_NAMES),
        "not_synced_dir": NOT_SYNCED_DIR,
        "max_file_bytes": MAX_FILE_BYTES,
    }
