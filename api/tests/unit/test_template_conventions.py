import pytest
from hamcrest import assert_that, equal_to

from api.domains.templates.conventions import (
    END_MARKER,
    START_MARKER,
    ConventionsSectionMalformed,
    merge_conventions,
)

SECTION = f"""{START_MARKER}
## Organization conventions

These apply to every Agent in this organization, whatever its role.

- Use Vilnius time for dates and deadlines.
{END_MARKER}
"""


def test_a_new_section_is_added_after_the_existing_instructions():
    merged, added = merge_conventions("# Agents\n\nBe helpful.\n", ["Use Vilnius time for dates and deadlines."])

    assert_that(merged, equal_to(f"# Agents\n\nBe helpful.\n\n{SECTION}"))
    assert_that(added, equal_to(1))


def test_an_empty_agents_md_becomes_the_section():
    merged, _ = merge_conventions("", ["Use Vilnius time for dates and deadlines."])

    assert_that(merged, equal_to(SECTION))


def test_new_rules_join_the_existing_section_and_text_around_it_is_kept():
    agents_md = f"# Agents\n\n{SECTION}\n## After\n\nKeep this.\n"

    merged, added = merge_conventions(agents_md, ["Ask before changing records."])

    assert_that(
        merged,
        equal_to(
            "# Agents\n\n"
            + SECTION.replace(END_MARKER, f"- Ask before changing records.\n{END_MARKER}")
            + "\n## After\n\nKeep this.\n"
        ),
    )
    assert_that(added, equal_to(1))


def test_rules_already_present_are_skipped_regardless_of_case_spacing_and_full_stop():
    merged, added = merge_conventions(SECTION, ["use  VILNIUS time for dates and deadlines", "Ask first.", "ask first"])

    assert_that(added, equal_to(1))
    assert_that(merged.count("Ask first"), equal_to(1))
    assert_that(merged.count("Vilnius"), equal_to(1))


def test_nothing_new_leaves_the_text_untouched():
    merged, added = merge_conventions(SECTION + "trailing", ["Use Vilnius time for dates and deadlines."])

    assert_that((merged, added), equal_to((SECTION + "trailing", 0)))


def test_rules_a_person_edited_inside_the_section_are_kept():
    edited = SECTION.replace("- Use Vilnius", "* Always use Vilnius")

    merged, _ = merge_conventions(edited, ["Ask before changing records."])

    assert_that("* Always use Vilnius time" in merged, equal_to(True))


@pytest.mark.parametrize(
    "agents_md",
    [f"{START_MARKER}\n- rule\n", f"- rule\n{END_MARKER}\n", f"{END_MARKER}\n{START_MARKER}\n"],
)
def test_a_section_with_broken_markers_is_refused(agents_md):
    with pytest.raises(ConventionsSectionMalformed):
        merge_conventions(agents_md, ["Ask first."])
