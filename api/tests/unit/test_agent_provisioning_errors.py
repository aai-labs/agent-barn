from __future__ import annotations

import json

from hamcrest import assert_that, contains_string, equal_to, is_, is_not, none

from api.domains.agents.provisioning_errors import (
    AgentProvisioningErrorCategory,
    normalize_agent_provisioning_error,
    persisted_provisioning_error,
)


class _ApiException(Exception):
    """Stands in for kubernetes.client.ApiException, which carries status + body."""

    def __init__(self, status: int | None, body: str) -> None:
        super().__init__(body)
        self.status = status
        self.body = body


def _status_body(message: str, *, reason: str, code: int) -> str:
    return json.dumps({"kind": "Status", "status": "Failure", "message": message, "reason": reason, "code": code})


def _pvc_quota_rejection() -> _ApiException:
    """A PVC refused by an exhausted storage quota, in the shape Kubernetes reports it."""
    return _ApiException(
        403,
        _status_body(
            'persistentvolumeclaims "agent-6f1c9e52-2b47-4c8a-9d1e-3f5b7c0a4e21" is forbidden: '
            "exceeded quota: example-quota, requested: requests.storage=1Gi, "
            "used: requests.storage=30Gi, limited: requests.storage=30Gi",
            reason="Forbidden",
            code=403,
        ),
    )


def test_exhausted_quota_names_the_exhausted_axis() -> None:
    """Which axis ran out is the whole diagnosis: storage and memory need different fixes."""
    normalized = normalize_agent_provisioning_error(_pvc_quota_rejection())

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.QUOTA_EXHAUSTED))
    assert_that(normalized.code, equal_to("QUOTA_EXHAUSTED"))
    assert_that(
        normalized.detail,
        equal_to(
            "requests.storage: requested 1Gi, used 30Gi, limit 30Gi "
            "(quota example-quota, creating persistentvolumeclaims)"
        ),
    )


def test_exhausted_quota_is_not_reported_as_an_rbac_problem() -> None:
    """A full ResourceQuota and a missing RoleBinding are both 403 Forbidden. Sending
    an operator to check service-account RBAC when the namespace is simply out of
    storage costs real debugging time."""
    normalized = normalize_agent_provisioning_error(_pvc_quota_rejection())

    assert_that(normalized.summary.casefold(), contains_string("quota"))
    assert_that(normalized.summary, is_not(contains_string("RBAC")))


def test_quota_detail_reports_every_exhausted_axis_of_a_comma_continued_list() -> None:
    exc = _ApiException(
        403,
        _status_body(
            'pods "agent-x" is forbidden: exceeded quota: example-quota, '
            "requested: requests.cpu=2,requests.memory=4Gi, "
            "used: requests.cpu=8,requests.memory=16Gi, "
            "limited: requests.cpu=8,requests.memory=16Gi",
            reason="Forbidden",
            code=403,
        ),
    )

    normalized = normalize_agent_provisioning_error(exc)

    assert normalized.detail is not None
    assert_that(normalized.detail, contains_string("requests.cpu: requested 2, used 8, limit 8"))
    assert_that(normalized.detail, contains_string("requests.memory: requested 4Gi, used 16Gi, limit 16Gi"))


def test_rbac_denial_names_the_denied_verb_without_republishing_the_service_account() -> None:
    exc = _ApiException(
        403,
        _status_body(
            'deployments.apps is forbidden: User "system:serviceaccount:agent-farm:agentbarn-api" '
            'cannot create resource "deployments" in API group "apps" in the namespace "agent-farm"',
            reason="Forbidden",
            code=403,
        ),
    )

    normalized = normalize_agent_provisioning_error(exc)

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED))
    assert_that(normalized.summary, contains_string("RBAC"))
    assert_that(normalized.detail, equal_to("cannot create deployments"))
    assert_that(normalized.display_message, is_not(contains_string("system:serviceaccount")))


def test_rejected_manifest_is_reported_as_an_invalid_definition() -> None:
    exc = _ApiException(
        422,
        _status_body(
            'Deployment.apps "agent-x" is invalid: spec.template.spec.containers[0].resources.limits: '
            "Invalid value: memory",
            reason="Invalid",
            code=422,
        ),
    )

    normalized = normalize_agent_provisioning_error(exc)

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.RESOURCE_REJECTED))


def test_a_summary_says_whether_retrying_helps_or_an_administrator_is_needed() -> None:
    """A user who cannot clear the failure should be told so, rather than retrying a
    start that will be refused identically every time."""
    quota = normalize_agent_provisioning_error(_pvc_quota_rejection())
    unreachable = normalize_agent_provisioning_error(ConnectionError("Max retries exceeded"))

    assert_that(quota.summary, contains_string("Ask an administrator"))
    assert_that(unreachable.summary, contains_string("try again"))
    assert_that(unreachable.summary, is_not(contains_string("administrator")))


def test_a_server_error_is_not_reported_as_an_unreachable_namespace() -> None:
    """A 5xx is the API server answering, so "could not be reached — try again in a
    moment" would assert a cause nothing established."""
    normalized = normalize_agent_provisioning_error(
        _ApiException(500, _status_body("failed to pull image x:1.0: manifest unknown", reason="X", code=500))
    )

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.UNKNOWN))
    assert_that(normalized.summary, is_not(contains_string("could not be reached")))


def test_an_unreachable_api_server_is_distinguished_from_a_rejected_request() -> None:
    exc = ConnectionError("HTTPSConnectionPool(host='10.0.0.1', port=443): Max retries exceeded")

    normalized = normalize_agent_provisioning_error(exc)

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE))


def test_an_unexpected_failure_falls_back_to_generic_copy_and_its_exception_type() -> None:
    """The raw text is dropped, so the exception class is the one clue left to a reader.
    The full exception still reaches the logs at the call site."""
    normalized = normalize_agent_provisioning_error(ValueError("builder produced an unusable manifest"))

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.UNKNOWN))
    assert_that(normalized.code, equal_to("PROVISIONING_FAILED"))
    assert_that(normalized.detail, equal_to("ValueError"))
    assert_that(normalized.display_message, is_not(contains_string("unusable manifest")))


def test_cluster_text_quoting_a_secret_value_never_reaches_the_normalized_error() -> None:
    """Kubernetes echoes request content back in rejections. A Secret value, a bearer
    token, or kubeconfig content in that text must not become a user-visible field."""
    leaked = "ghp_liveGithubTokenValue000000000000"
    exc = _ApiException(
        422,
        _status_body(
            f'Secret "agent-x" is invalid: data.token: Invalid value: "{leaked}": '
            "must be base64; also authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
            reason="Invalid",
            code=422,
        ),
    )

    normalized = normalize_agent_provisioning_error(exc)

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.RESOURCE_REJECTED))
    assert_that(normalized.display_message, is_not(contains_string(leaked)))
    assert_that(normalized.display_message, is_not(contains_string("eyJhbGciOiJIUzI1NiJ9")))
    assert_that(normalized.display_message, is_not(contains_string("Bearer")))


def test_the_redaction_gate_drops_a_detail_it_cannot_vouch_for_and_keeps_the_summary() -> None:
    """`count/secrets` is a real ResourceQuota axis, so the gate over-redacts here and
    the axis name is lost. That is the intended trade: a coarse gate that occasionally
    costs a line of diagnosis beats one that occasionally publishes a credential. The
    user is still told, correctly, that quota is what stopped the Agent."""
    exc = _ApiException(
        403,
        _status_body(
            'secrets "agent-x" is forbidden: exceeded quota: example-quota, '
            "requested: count/secrets=1, used: count/secrets=50, limited: count/secrets=50",
            reason="Forbidden",
            code=403,
        ),
    )

    normalized = normalize_agent_provisioning_error(exc)

    assert_that(normalized.category, is_(AgentProvisioningErrorCategory.QUOTA_EXHAUSTED))
    assert_that(normalized.detail, is_(none()))
    assert_that(normalized.display_message, equal_to(normalized.summary))
    assert_that(normalized.display_message.casefold(), contains_string("quota"))


def test_a_classified_failure_carries_no_exception_type_noise() -> None:
    """`(ApiException)` on a user-facing banner is noise; the summary already says more.
    Only the unclassified case falls back to the exception's type."""
    exc = _ApiException(422, _status_body('Deployment.apps "agent-x" is invalid: spec', reason="Invalid", code=422))

    assert_that(normalize_agent_provisioning_error(exc).detail, is_(none()))


def test_a_stored_failure_derives_its_copy_from_the_code_not_from_stored_text() -> None:
    """Only the code and detail are trusted from storage, so improved copy and a
    improved copy reaches Agents already sitting in ERROR without a data migration."""
    stored = persisted_provisioning_error(
        code="QUOTA_EXHAUSTED",
        detail="requests.storage: requested 1Gi, used 30Gi, limit 30Gi",
        legacy_message="whatever was rendered when this row was written",
    )

    assert_that(stored, is_not(none()))
    assert stored is not None
    assert_that(stored.category, is_(AgentProvisioningErrorCategory.QUOTA_EXHAUSTED))
    # A failure read back from the database and one just classified read identically.
    assert_that(stored.summary, equal_to(normalize_agent_provisioning_error(_pvc_quota_rejection()).summary))
    assert stored.detail is not None
    assert_that(stored.detail, contains_string("requests.storage"))


def test_a_row_written_before_normalization_never_shows_its_unsanitized_text() -> None:
    """Staging already holds raw Kubernetes text in `agent.last_error` from before this
    contract existed. A row with no code is exactly that, so its message is dropped
    and the failure is reported as unclassified rather than published verbatim."""
    stored = persisted_provisioning_error(
        code=None,
        detail=None,
        legacy_message='pods "agent-x" forbidden: secret "api-token" is sk_live_realvalue',
    )

    assert_that(stored, is_not(none()))
    assert stored is not None
    assert_that(stored.category, is_(AgentProvisioningErrorCategory.UNKNOWN))
    assert_that(stored.detail, is_(none()))
    assert_that(stored.display_message, is_not(contains_string("sk_live_realvalue")))


def test_an_agent_that_never_failed_has_no_stored_error() -> None:
    assert_that(persisted_provisioning_error(code=None, detail=None, legacy_message=None), is_(none()))


def test_an_unrecognized_stored_code_degrades_to_the_generic_failure() -> None:
    """A code written by a newer version, or corrupted in place, must not break the read."""
    stored = persisted_provisioning_error(code="SOMETHING_ELSE", detail=None, legacy_message=None)

    assert stored is not None
    assert_that(stored.category, is_(AgentProvisioningErrorCategory.UNKNOWN))


def test_a_stored_detail_is_re_screened_rather_than_trusted() -> None:
    """The write path sanitizes, and the read path sanitizes again, so a detail
    written by any future path that skips normalization still cannot reach a client."""
    stored = persisted_provisioning_error(
        code="QUOTA_EXHAUSTED",
        detail="authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        legacy_message=None,
    )

    assert stored is not None
    assert_that(stored.detail, is_(none()))
