import re
import secrets

SLUG_LIMIT = 32
TOKEN_BYTES = 2
FALLBACK_SLUG = "agent"
NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def build_local_part(agent_name: str) -> str:
    slug = NON_SLUG_RUN.sub("-", agent_name.lower()).strip("-")[:SLUG_LIMIT].strip("-")
    return f"{slug or FALLBACK_SLUG}-{secrets.token_hex(TOKEN_BYTES)}"


def compose_address(mailbox: str, local_part: str, domain: str) -> str:
    return f"{mailbox}+{local_part}@{domain}"


def extract_local_part(mailbox: str, address: str) -> str:
    local, _, domain = address.strip().lower().partition("@")
    if not domain:
        return ""
    prefix, separator, tag = local.partition("+")
    if not separator or prefix != mailbox.strip().lower():
        return ""
    return tag
