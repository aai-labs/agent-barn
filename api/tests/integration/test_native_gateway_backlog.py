from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from api.domains.communications.operations import CommunicationOperationalRepository
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.helpers.agent_messages import STEPS
from api.tests.steps.communication import there_is_a_connection, there_is_an_inbound_delivery


@pytest.mark.parametrize("platform_key", ["slack", "discord", "telegram", "teams", "web", "email"])
def test_only_gateway_work_counts_as_live_backlog_while_history_remains_visible(platform_key):
    with given([*STEPS, there_is_a_connection(), there_is_an_inbound_delivery()]) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            connection = session.get(type(context.connection), context.connection.id)
            assert connection is not None
            connection.platform_key = platform_key
            session.add(connection)
            session.commit()
        operations = context.injector.get(CommunicationOperationalRepository)
        summary = operations.diagnostics_snapshot(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            connection_id=context.connection.id,
            authorization_scope=AuthorizationScope(organization_id=context.organization.id),
            window_start=datetime.now(UTC) - timedelta(days=1),
            window_end=datetime.now(UTC),
        )
        gateway = platform_key in {"web", "email"}
        assert summary.queue_depth == (1 if gateway else 0)
        assert (summary.oldest_queued_age_seconds is not None) is gateway
        assert (summary.oldest_pending_delivery_age_seconds is not None) is gateway
        assert summary.delivery_counts.pending == 1
        metrics = operations.get_metrics_snapshot()
        assert sum(count for _, count, _ in metrics.queued_deliveries) == (1 if gateway else 0)
        response = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{context.connection.id}/summary",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["queue_depth"] == (1 if gateway else 0)
        assert response.json()["delivery_counts"]["pending"] == 1
