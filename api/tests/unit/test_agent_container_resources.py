"""An Agent Size as the agent container's resources block."""

import pytest

from api.domains.agent_sizes.models import (
    STANDARD_CPU_LIMIT_MILLICORES,
    STANDARD_CPU_REQUEST_MILLICORES,
    STANDARD_MEMORY_LIMIT_BYTES,
    STANDARD_MEMORY_REQUEST_BYTES,
)
from api.domains.agents.builders.common import INIT_CONTAINER_RESOURCES, container_resources

_MIB = 1024**2
_GIB = 1024**3


def test_the_standard_size_renders_exactly_what_agents_ran_with_before_sizes() -> None:
    """The same strings, not just equal quantities: the pod spec of every Agent is unchanged."""
    resources = container_resources(
        cpu_request_millicores=STANDARD_CPU_REQUEST_MILLICORES,
        cpu_limit_millicores=STANDARD_CPU_LIMIT_MILLICORES,
        memory_request_bytes=STANDARD_MEMORY_REQUEST_BYTES,
        memory_limit_bytes=STANDARD_MEMORY_LIMIT_BYTES,
    )

    assert resources.requests == {"memory": "320Mi", "cpu": "50m"}
    assert resources.limits == {"memory": "1Gi", "cpu": "500m"}
    assert resources == INIT_CONTAINER_RESOURCES


@pytest.mark.parametrize(
    ("memory", "expected"),
    [(512 * _MIB, "512Mi"), (16 * _GIB, "16Gi"), (1536 * _MIB, "1536Mi"), (1_000_000_001, "1000000001")],
)
def test_memory_is_written_in_gi_or_mi_when_whole_and_in_bytes_otherwise(memory: int, expected: str) -> None:
    resources = container_resources(
        cpu_request_millicores=1000,
        cpu_limit_millicores=1000,
        memory_request_bytes=memory,
        memory_limit_bytes=memory,
    )

    assert resources.requests == {"memory": expected, "cpu": "1000m"}
