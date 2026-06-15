import re
import secrets

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_MAX_BASE_LENGTH = 64


def slugify(name: str) -> str:
    """Lowercase, replace non-alphanumerics with '-', e.g. 'Scrum Master' -> 'scrum-master'."""
    return (
        _NON_SLUG_CHARS.sub("-", name.lower()).strip("-")[:_MAX_BASE_LENGTH].strip("-")
    )


def generate_template_slug(name: str) -> str:
    """slugify(name) + '-' + 8-char random hex, e.g. 'maya-3f9a2c1b'."""
    base = slugify(name)
    suffix = secrets.token_hex(4)
    return f"{base}-{suffix}" if base else suffix
