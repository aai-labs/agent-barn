import yaml
from hamcrest import assert_that, equal_to

from api.domains.playbooks.prompts import Playbook, skill_markdown


def _frontmatter(markdown: str) -> dict:
    return yaml.safe_load(markdown.split("---\n")[1])


def test_a_description_with_a_backslash_survives_the_frontmatter():
    playbook = Playbook(description=r"Use for paths like C:\reports\new and \d patterns.", body="# Body")

    assert_that(
        _frontmatter(skill_markdown("reports", playbook)),
        equal_to({"name": "reports", "description": r"Use for paths like C:\reports\new and \d patterns."}),
    )


def test_double_quotes_in_a_description_cannot_end_the_scalar():
    playbook = Playbook(description='Use when someone says "refund".', body="# Body")

    assert_that(
        _frontmatter(skill_markdown("refunds", playbook))["description"], equal_to("Use when someone says 'refund'.")
    )
