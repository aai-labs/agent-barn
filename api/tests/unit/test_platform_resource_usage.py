from uuid import UUID, uuid4

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
