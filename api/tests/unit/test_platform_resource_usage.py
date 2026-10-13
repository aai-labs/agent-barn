from uuid import UUID, uuid4

import pytest

from api.domains.agents.models import AgentStatus, PlatformAgentIdentity
from api.domains.resource_usage.platform_service import build_platform_usage, count_with_container

_ACME = UUID("00000000-0000-7000-8000-0000000000aa")
_GLOBEX = UUID("00000000-0000-7000-8000-0000000000bb")
_GiB = 1024**3


def _agent(name: str, organization_id: UUID, status: AgentStatus = AgentStatus.RUNNING) -> PlatformAgentIdentity:
    organization_name = "Acme" if organization_id == _ACME else "Globex"
    return PlatformAgentIdentity(uuid4(), name, status, organization_id, organization_name)


def _reading(memory_gib: float, cpu: float, *, throttled: float = 0.0) -> dict[str, float]:
    return {
        "up": 1.0,
        "cgroup_metrics_available": 1.0,
        "memory_working_set_bytes": memory_gib * _GiB,
        "memory_limit_bytes": 2.0 * _GiB,
        "cpu_cores": cpu,
        "cpu_limit_cores": 1.0,
        "cpu_throttled_ratio": throttled,
    }


def test_the_platform_totals_add_up_every_reporting_agent():
    ada, bob, cy = _agent("Ada", _ACME), _agent("Bob", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage(
        [ada, bob, cy],
        {ada.id: _reading(1.0, 0.2), bob.id: _reading(0.5, 0.1), cy.id: _reading(0.25, 0.05)},
    )

    assert usage.totals.agents_with_container == 3
    assert usage.totals.agents_reporting == 3
    assert usage.totals.memory_working_set_bytes == int(1.75 * _GiB)
    assert usage.totals.memory_limit_bytes == 6 * _GiB
    assert usage.totals.cpu_cores is not None and abs(usage.totals.cpu_cores - 0.35) < 1e-9
    assert usage.totals.cpu_limit_cores == 3.0


def test_each_organization_is_summed_and_named_from_the_database_heaviest_first():
    ada, bob, cy = _agent("Ada", _ACME), _agent("Bob", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage(
        [ada, bob, cy],
        {ada.id: _reading(0.25, 0.2), bob.id: _reading(0.25, 0.1), cy.id: _reading(1.0, 0.05)},
    )

    assert [row.organization_name for row in usage.organizations] == ["Globex", "Acme"]
    acme = usage.organizations[1]
    assert acme.organization_id == _ACME
    assert acme.agents_with_container == 2
    assert acme.agents_reporting == 2
    assert acme.memory_working_set_bytes == int(0.5 * _GiB)


def test_agents_are_listed_heaviest_memory_first_with_their_organization():
    ada, cy = _agent("Ada", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage([ada, cy], {ada.id: _reading(0.5, 0.9, throttled=0.4), cy.id: _reading(1.0, 0.1)})

    assert [row.agent_name for row in usage.agents] == ["Cy", "Ada"]
    assert usage.agents[1].organization_name == "Acme"
    assert usage.agents[1].cpu_throttled_ratio == 0.4
    assert usage.agents[1].memory_limit_bytes == 2 * _GiB


def test_a_container_with_no_live_agent_gets_its_own_bucket_last():
    ada = _agent("Ada", _ACME)
    orphan = uuid4()

    usage = build_platform_usage([ada], {ada.id: _reading(0.25, 0.1), orphan: _reading(2.0, 0.1)})

    assert [row.organization_name for row in usage.organizations] == ["Acme", None]
    leaked = usage.organizations[-1]
    assert leaked.organization_id is None
    assert leaked.agents_with_container == 0
    assert leaked.agents_reporting == 1
    # It still counts toward the platform, so the rows add up to the total.
    assert usage.totals.memory_working_set_bytes == int(2.25 * _GiB)
    orphan_row = next(row for row in usage.agents if row.agent_id == orphan)
    assert orphan_row.agent_name is None
    assert orphan_row.organization_id is None


def test_a_filter_narrows_the_totals_and_agents_but_not_the_organizations():
    ada, cy = _agent("Ada", _ACME), _agent("Cy", _GLOBEX)
    orphan = uuid4()

    usage = build_platform_usage(
        [ada, cy],
        {ada.id: _reading(0.5, 0.2), cy.id: _reading(1.0, 0.1), orphan: _reading(2.0, 0.1)},
        organization_id=_ACME,
    )

    assert usage.totals.agents_reporting == 1
    assert usage.totals.memory_working_set_bytes == int(0.5 * _GiB)
    assert [row.agent_name for row in usage.agents] == ["Ada"]
    assert len(usage.organizations) == 3


def test_a_filter_on_an_organization_with_nothing_running_is_all_zero():
    ada = _agent("Ada", _ACME)

    usage = build_platform_usage([ada], {ada.id: _reading(0.5, 0.2)}, organization_id=_GLOBEX)

    assert usage.totals.agents_with_container == 0
    assert usage.totals.agents_reporting == 0
    assert usage.totals.memory_working_set_bytes == 0
    assert usage.agents == []


def test_stopped_agents_have_no_container_even_if_a_late_reading_comes_in():
    ada = _agent("Ada", _ACME)
    stopped = _agent("Stopped", _ACME, AgentStatus.STOPPED)
    errored = _agent("Errored", _ACME, AgentStatus.ERROR)

    usage = build_platform_usage([ada, stopped, errored], {ada.id: _reading(0.5, 0.2), stopped.id: _reading(1.0, 0.1)})

    assert usage.totals.agents_with_container == 2
    assert usage.totals.agents_reporting == 1
    assert [row.agent_name for row in usage.agents] == ["Ada"]


def test_a_scrape_without_cpu_or_memory_is_not_reporting():
    ada, bob = _agent("Ada", _ACME), _agent("Bob", _ACME)

    usage = build_platform_usage(
        [ada, bob],
        {ada.id: _reading(0.5, 0.2), bob.id: {"up": 1.0, "cgroup_metrics_available": 0.0}},
    )

    assert usage.totals.agents_with_container == 2
    assert usage.totals.agents_reporting == 1
    assert [row.agent_name for row in usage.agents] == ["Ada"]


def test_containers_are_counted_from_the_database_with_or_without_a_filter():
    agents = [
        _agent("Ada", _ACME),
        _agent("Bob", _ACME, AgentStatus.ERROR),
        _agent("Cy", _GLOBEX),
        _agent("Stopped", _GLOBEX, AgentStatus.STOPPED),
    ]

    assert count_with_container(agents, None) == 3
    assert count_with_container(agents, _ACME) == 2
    assert count_with_container(agents, _GLOBEX) == 1


def _scraped_before_usage_existed() -> dict[str, float]:
    """What an Agent on an older healthz script shows: scraped, with no usage gauge at all."""
    return {"up": 1.0}


def test_an_agent_on_an_older_healthz_script_is_counted_as_needing_an_update():
    ada, bob, cy = _agent("Ada", _ACME), _agent("Bob", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage(
        [ada, bob, cy],
        {ada.id: _reading(0.5, 0.2), bob.id: _scraped_before_usage_existed(), cy.id: _scraped_before_usage_existed()},
    )

    assert usage.totals.agents_reporting == 1
    assert usage.totals.agents_restart_required == 2
    by_name = {row.organization_name: row for row in usage.organizations}
    assert by_name["Acme"].agents_restart_required == 1
    assert by_name["Globex"].agents_restart_required == 1
    # It has nothing to show, so it is not a row of the table.
    assert [row.agent_name for row in usage.agents] == ["Ada"]


def test_only_a_live_agent_with_a_container_can_need_an_update():
    ada = _agent("Ada", _ACME)
    stopped = _agent("Stopped", _ACME, AgentStatus.STOPPED)
    unknown = uuid4()

    usage = build_platform_usage(
        [ada, stopped],
        {
            ada.id: _scraped_before_usage_existed(),
            # A late scrape of a stopped agent, and a container no live agent owns: neither
            # has an owner who could update it.
            stopped.id: _scraped_before_usage_existed(),
            unknown: _scraped_before_usage_existed(),
        },
    )

    assert usage.totals.agents_restart_required == 1


def test_a_reporting_or_unsupported_agent_does_not_need_an_update():
    ada, bob = _agent("Ada", _ACME), _agent("Bob", _ACME)

    usage = build_platform_usage(
        [ada, bob],
        {ada.id: _reading(0.5, 0.2), bob.id: {"up": 1.0, "cgroup_metrics_available": 0.0}},
    )

    assert usage.totals.agents_restart_required == 0


def test_the_filter_narrows_the_update_count_with_the_rest_of_the_totals():
    ada, cy = _agent("Ada", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage(
        [ada, cy],
        {ada.id: _scraped_before_usage_existed(), cy.id: _scraped_before_usage_existed()},
        organization_id=_ACME,
    )

    assert usage.totals.agents_restart_required == 1
    # The organizations stay the whole platform, as the table beside them does.
    assert [row.agents_restart_required for row in usage.organizations] == [1, 1]


def _with_requests(readings: dict[str, float], memory_gib: float, cpu: float) -> dict[str, float]:
    return {**readings, "memory_request_bytes": memory_gib * _GiB, "cpu_request_cores": cpu}


def test_requests_sit_on_each_agent_row_and_add_up_by_organization_and_overall():
    ada, bob, cy = _agent("Ada", _ACME), _agent("Bob", _ACME), _agent("Cy", _GLOBEX)

    usage = build_platform_usage(
        [ada, bob, cy],
        {
            ada.id: _with_requests(_reading(0.5, 0.2), 0.25, 0.05),
            bob.id: _with_requests(_reading(1.0, 0.1), 0.5, 0.1),
            cy.id: _with_requests(_reading(1.5, 0.3), 0.125, 0.05),
        },
    )

    row = {agent.agent_name: agent for agent in usage.agents}
    assert row["Ada"].memory_request_bytes == int(0.25 * _GiB)
    assert row["Ada"].cpu_request_cores == 0.05
    acme = next(org for org in usage.organizations if org.organization_name == "Acme")
    assert acme.memory_request_bytes == int(0.75 * _GiB)
    assert acme.cpu_request_cores == pytest.approx(0.15)
    assert usage.totals.memory_request_bytes == int(0.875 * _GiB)
    assert usage.totals.cpu_request_cores == pytest.approx(0.2)


def test_requests_that_could_not_be_read_are_unknown_not_zero():
    ada = _agent("Ada", _ACME)

    usage = build_platform_usage([ada], {ada.id: _reading(0.5, 0.2)})

    assert usage.agents[0].memory_request_bytes is None
    assert usage.agents[0].cpu_request_cores is None
    assert usage.totals.memory_request_bytes is None
    assert usage.totals.cpu_request_cores is None
    assert usage.organizations[0].memory_request_bytes is None


def test_one_agent_without_a_request_does_not_blank_the_rest():
    ada, bob = _agent("Ada", _ACME), _agent("Bob", _ACME)

    usage = build_platform_usage(
        [ada, bob], {ada.id: _with_requests(_reading(0.5, 0.2), 0.25, 0.05), bob.id: _reading(1.0, 0.1)}
    )

    # Bob's pod is not up yet, say, so only Ada's request is in the sum, and Bob's row says nothing.
    assert usage.totals.memory_request_bytes == int(0.25 * _GiB)
    assert {a.agent_name: a.memory_request_bytes for a in usage.agents}["Bob"] is None


def test_a_request_for_an_agent_that_does_not_report_is_not_added_to_the_totals():
    ada, bob = _agent("Ada", _ACME), _agent("Bob", _ACME)

    usage = build_platform_usage(
        [ada, bob],
        {
            ada.id: _with_requests(_reading(0.5, 0.2), 0.25, 0.05),
            # Scraped but not reporting: the limits leave it out of the totals, so the request does too.
            bob.id: _with_requests({"up": 1.0}, 4.0, 2.0),
        },
    )

    assert usage.totals.memory_request_bytes == int(0.25 * _GiB)
    assert usage.totals.agents_restart_required == 1
