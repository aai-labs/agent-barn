from collections.abc import Collection

from api.domains.file_sync.rules import SKIP_DIR_NAMES, name_problem
from api.domains.personas.models import PERSONA_KEY_MAX_LENGTH
from api.domains.templates.slug import slugify

HERMES_RESERVED_NAMES = frozenset({"hermes", "default", "test", "tmp", "root", "sudo"})
FALLBACK_PREFIX = "persona"


def _usable(key: str) -> bool:
    return bool(key) and key not in HERMES_RESERVED_NAMES and key not in SKIP_DIR_NAMES and name_problem(key) is None


def _with_suffix(base: str, number: int) -> str:
    suffix = f"-{number}"
    return f"{base[: PERSONA_KEY_MAX_LENGTH - len(suffix)].rstrip('-')}{suffix}"


def derive_key(display_name: str, taken: Collection[str]) -> str:
    slug = slugify(display_name)[:PERSONA_KEY_MAX_LENGTH].rstrip("-")
    if not _usable(slug):
        number = 1
        while (candidate := _with_suffix(FALLBACK_PREFIX, number)) in taken:
            number += 1
        return candidate
    if slug not in taken:
        return slug
    number = 2
    while (candidate := _with_suffix(slug, number)) in taken:
        number += 1
    return candidate
