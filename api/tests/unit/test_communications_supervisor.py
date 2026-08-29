import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest

from api.core.config import Config
from api.domains.communications.models import (
    CommunicationConnection,
    ConnectionObservedStatus,
)
from api.domains.communications.supervisor import PlatformIngressSupervisor


def test_connection_setup_failure_records_error_health() -> None:
    connection = CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="missing",
        display_name="Broken Connection",
        credentials_encrypted="invalid",
        driver_key_encrypted="invalid",
    )
    connections = Mock()
    plugins = Mock()
    plugins.require.side_effect = KeyError("Unsupported communication platform: missing")
    supervisor = PlatformIngressSupervisor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="test-key")),
        connections=connections,
        gateway=Mock(),
        plugins=plugins,
    )

    async def exercise() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(supervisor._maintain(connection), timeout=0.05)

    asyncio.run(exercise())

    statuses = [call.args[1] for call in connections.record_health.call_args_list]
    assert statuses == [ConnectionObservedStatus.CONNECTING, ConnectionObservedStatus.ERROR]
    error_call = connections.record_health.call_args_list[-1]
    assert error_call.kwargs["error_code"] == "CONFIGURATION_ERROR"
    assert error_call.kwargs["error_details"].category.value == "configuration"
    assert error_call.kwargs["error_details"].operation == "ingress_session"
