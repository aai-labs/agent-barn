import json

from api.domains.agents.error_messages import friendly_k8s_error


class _ApiException(Exception):
    """Stands in for kubernetes.client.ApiException, which carries status + body."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(body)
        self.status = status
        self.body = body


def _quota_rejection() -> _ApiException:
    """Verbatim shape of a real ResourceQuota rejection: k8s returns 403 Forbidden,
    the same status as an RBAC denial."""
    return _ApiException(
        403,
        json.dumps(
            {
                "kind": "Status",
                "status": "Failure",
                "message": (
                    'pods "agent-x" is forbidden: exceeded quota: agents, '
                    "requested: limits.memory=2Gi, used: limits.memory=100Gi, "
                    "limited: limits.memory=100Gi"
                ),
                "reason": "Forbidden",
                "code": 403,
            }
        ),
    )


def test_quota_exhaustion_is_not_reported_as_an_rbac_problem() -> None:
    """A full namespace quota and a missing RoleBinding both surface as 403. Sending
    an operator to check service-account RBAC when the namespace is simply out of
    limits.memory costs real debugging time."""
    message = friendly_k8s_error(_quota_rejection())

    assert "quota" in message.lower()
    assert "RBAC" not in message
    assert "Permission denied" not in message


def test_quota_message_keeps_the_exhausted_resource_visible() -> None:
    """Which axis ran out is the whole diagnosis -- limits.memory and
    requests.memory need different fixes."""
    message = friendly_k8s_error(_quota_rejection())

    assert "limits.memory" in message


def test_genuine_rbac_denial_still_points_at_the_service_account() -> None:
    exc = _ApiException(
        403,
        json.dumps(
            {
                "message": 'deployments.apps is forbidden: User "system:serviceaccount:agent-farm:api" cannot create resource',
                "reason": "Forbidden",
                "code": 403,
            }
        ),
    )
    message = friendly_k8s_error(exc)

    assert "RBAC" in message
