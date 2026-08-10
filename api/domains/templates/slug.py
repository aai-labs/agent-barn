import re
import secrets

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")
_MAX_BASE_LENGTH = 64


def slugify(name: str) -> str:
    """Lowercase, replace non-alphanumerics with '-', e.g. 'Scrum Master' -> 'scrum-master'."""
    return _NON_SLUG_CHARS.sub("-", name.lower()).strip("-")[:_MAX_BASE_LENGTH].strip("-")


def generate_template_key() -> str:
    """Generate an opaque, URL-safe identifier for a new template lineage."""
    return f"tpl-{secrets.token_hex(6)}"
