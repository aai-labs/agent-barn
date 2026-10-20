"""The managed Organization Conventions section of a Template's AGENTS.md.

Runtimes write the Template's `agents_md` to AGENTS.md, which every Agent loads at
startup, so rules here apply to every Agent pinned to the Template version. The
section is delimited by markers so later additions merge into it instead of
appending another copy; people may edit the rules between the markers freely.
"""

import re

START_MARKER = "<!-- agentbarn:organization-conventions:start -->"
END_MARKER = "<!-- agentbarn:organization-conventions:end -->"
SECTION_HEADING = "## Organization conventions"
SECTION_INTRO = "These apply to every Agent in this organization, whatever its role."

_BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


class ConventionsSectionMalformed(ValueError):
    """Only one marker, or the end before the start: a person edited the markers by hand."""


def merge_conventions(agents_md: str, rules: list[str]) -> tuple[str, int]:
    """Add rules not already in the section, creating it at the end if absent.

    Returns the new text and how many rules were added. Rules match regardless of
    case, spacing, and a trailing full stop.
    """
    start, end = agents_md.find(START_MARKER), agents_md.find(END_MARKER)
    if (start == -1) != (end == -1) or (start != -1 and end < start):
        raise ConventionsSectionMalformed()

    existing_body = agents_md[start + len(START_MARKER) : end] if start != -1 else ""
    seen = {_key(match.group(1)) for line in existing_body.splitlines() if (match := _BULLET.match(line))}
    added: list[str] = []
    for rule in rules:
        text = " ".join(rule.split())
        if text and _key(text) not in seen:
            seen.add(_key(text))
            added.append(text)
    if not added:
        return agents_md, 0

    new_lines = "\n".join(f"- {rule}" for rule in added)
    if start == -1:
        section = f"{START_MARKER}\n{SECTION_HEADING}\n\n{SECTION_INTRO}\n\n{new_lines}\n{END_MARKER}\n"
        existing = agents_md.rstrip()
        return (f"{existing}\n\n{section}" if existing else section), len(added)

    body = existing_body.rstrip()
    merged_body = f"{body}\n{new_lines}\n" if body else f"\n{SECTION_HEADING}\n\n{SECTION_INTRO}\n\n{new_lines}\n"
    return agents_md[: start + len(START_MARKER)] + merged_body + agents_md[end:], len(added)


def _key(rule: str) -> str:
    return " ".join(rule.split()).rstrip(".").casefold()
