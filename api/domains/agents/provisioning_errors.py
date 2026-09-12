"""Safe, categorized diagnostics for Agent provisioning failures.

Kubernetes rejection text can name Secrets, quote kubeconfig fragments, and echo
request bodies, so nothing here forwards it to a client or stores it on the Agent.
A failure is classified into one category, and each category has fixed copy. The
only variable part is ``detail``, rebuilt from fragments matching strict patterns:
a quota axis, a Kubernetes quantity, a resource kind. Fragments that do not match
are dropped.

The full exception is written to the logs at the call site.
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass
from typing import Any

# Mirrors the sibling denylists in api/domains/communications/error_details.py and
# api/domains/events/constants.py. Each domain keeps its own copy so a domain's
# redaction rules cannot be loosened from outside it.
_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "kubeconfig",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)

MAX_PROVISIONING_DETAIL_CHARS = 500


class AgentProvisioningErrorCategory(str, enum.Enum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    CLUSTER_PERMISSION_DENIED = "cluster_permission_denied"
    RESOURCE_REJECTED = "resource_rejected"
    CLUSTER_UNAVAILABLE = "cluster_unavailable"
    UNKNOWN = "unknown"


_ERROR_CODES: dict[AgentProvisioningErrorCategory, str] = {
    AgentProvisioningErrorCategory.QUOTA_EXHAUSTED: "QUOTA_EXHAUSTED",
    AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED: "CLUSTER_PERMISSION_DENIED",
    AgentProvisioningErrorCategory.RESOURCE_REJECTED: "RESOURCE_REJECTED",
    AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE: "CLUSTER_UNAVAILABLE",
    AgentProvisioningErrorCategory.UNKNOWN: "PROVISIONING_FAILED",
}

_CATEGORY_BY_CODE: dict[str, AgentProvisioningErrorCategory] = {
    code: category for category, code in _ERROR_CODES.items()
}

_SUMMARY_BY_CATEGORY: dict[AgentProvisioningErrorCategory, str] = {
    AgentProvisioningErrorCategory.QUOTA_EXHAUSTED: (
        "The agent could not start — its namespace has run out of resource quota. "
        "Ask an administrator to free up or raise it, then start the agent again."
    ),
    AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED: (
        "The agent could not start — Agent Barn's service account is missing RBAC permission to "
        "create the agent's resources. Ask an administrator to review them."
    ),
    AgentProvisioningErrorCategory.RESOURCE_REJECTED: (
        "The agent could not start — the cluster rejected its resource definition as invalid. "
        "Ask an administrator to review the agent's runtime configuration."
    ),
    AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE: (
        "The agent could not start — its Kubernetes namespace could not be reached. "
        "This is often temporary, so try again in a moment."
    ),
    AgentProvisioningErrorCategory.UNKNOWN: (
        "The agent could not start — creating its runtime resources failed unexpectedly. "
        "Try again; if it keeps failing, ask an administrator to check the cluster."
    ),
}

# A ResourceQuota axis ("requests.storage", "limits.memory", "count/pods")
# paired with a Kubernetes quantity ("1Gi", "30", "1500m").
_QUOTA_PAIR = re.compile(
    r"(?:(requested|used|limited):\s*)?([a-z][a-z0-9./-]{0,63})=([0-9]+(?:\.[0-9]+)?[A-Za-z]{0,2})(?![A-Za-z0-9.])"
)
_QUOTA_NAME = re.compile(r"exceeded quota:\s*([a-z0-9][a-z0-9.-]{0,62})\s*,")
_RESOURCE_KIND = re.compile(r'^([a-z][a-z0-9.]{0,62})\s+"')
_RBAC_RESOURCE = re.compile(
    r'cannot\s+(create|get|update|delete|list|watch|patch)\s+resource\s+"([a-z][a-z0-9.-]{0,62})"'
)
_EXCEPTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_QUOTA_KEYWORD_LABELS = (("requested", "requested"), ("used", "used"), ("limited", "limit"))
_MAX_REPORTED_QUOTA_AXES = 3


@dataclass(frozen=True)
class NormalizedAgentProvisioningError:
    """A provisioning failure in the form the service returns and stores."""

    code: str
    category: AgentProvisioningErrorCategory
    summary: str
    detail: str | None

    @property
    def display_message(self) -> str:
        """Summary and detail as one line, for surfaces that carry a single string."""
        return f"{self.summary} ({self.detail})" if self.detail else self.summary


def normalize_agent_provisioning_error(exc: Exception) -> NormalizedAgentProvisioningError:
    """Classify a provisioning failure and rebuild a safe, bounded detail for it."""
    status_code = _status_code_of(exc)
    message = _cluster_message(exc)
    category = _classify(exc, status_code=status_code, message=message)
    return _for_category(category, detail=_detail_for(category, message=message, exc=exc))


def persisted_provisioning_error(
    *,
    code: str | None,
    detail: str | None,
    legacy_message: str | None,
) -> NormalizedAgentProvisioningError | None:
    """Rebuild a stored failure at the read boundary.

    Only the code and detail are trusted from storage. The summary is derived here,
    so improved copy reaches Agents already sitting in ERROR without a data migration.

    A row with no code but a message was written before normalization existed. Its
    text came straight from the cluster, so it is reported as an unclassified
    failure and the stored text is dropped.
    """
    if code is None:
        return _for_category(AgentProvisioningErrorCategory.UNKNOWN, detail=None) if legacy_message else None
    category = _CATEGORY_BY_CODE.get(code, AgentProvisioningErrorCategory.UNKNOWN)
    return _for_category(category, detail=_bounded_safe_detail(detail))


def _for_category(
    category: AgentProvisioningErrorCategory,
    *,
    detail: str | None,
) -> NormalizedAgentProvisioningError:
    return NormalizedAgentProvisioningError(
        code=_ERROR_CODES[category],
        category=category,
        summary=_SUMMARY_BY_CATEGORY[category],
        detail=detail,
    )


def _status_code_of(exc: Exception) -> int | None:
    status_code = getattr(exc, "status", None)
    return status_code if isinstance(status_code, int) else None


def _cluster_message(exc: Exception) -> str:
    """The cluster's own message, used only for classification and pattern extraction.

    Never returned to a caller. ``ApiException.body`` is a JSON Status object; the
    exception's own text is the fallback when it is absent or unparseable.
    """
    body: Any = getattr(exc, "body", None)
    if body:
        try:
            parsed = json.loads(body) if isinstance(body, (str, bytes)) else body
        except TypeError, ValueError:
            parsed = None
        if isinstance(parsed, dict):
            message = parsed.get("message") or parsed.get("reason")
            if isinstance(message, str) and message:
                return message
        if isinstance(body, str):
            return body
    return str(exc)


def _classify(
    exc: Exception,
    *,
    status_code: int | None,
    message: str,
) -> AgentProvisioningErrorCategory:
    lowered = message.casefold()

    # A full ResourceQuota and a missing RoleBinding both come back as 403 Forbidden.
    # Reporting quota exhaustion as an RBAC fault sends operators to the service
    # account when the namespace has simply run out of a resource, so quota wins.
    if "exceeded quota" in lowered or "resourcequota" in lowered:
        return AgentProvisioningErrorCategory.QUOTA_EXHAUSTED
    if status_code == 403 or "forbidden" in lowered or "cannot create resource" in lowered:
        return AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED
    if status_code == 422 or "is invalid" in lowered or "unprocessable" in lowered:
        return AgentProvisioningErrorCategory.RESOURCE_REJECTED
    if status_code == 404 or "not found" in lowered:
        return AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE
    if status_code is None and _looks_unreachable(exc, lowered):
        return AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE
    # A 5xx means the API server answered, so the namespace is reachable.
    return AgentProvisioningErrorCategory.UNKNOWN


_UNREACHABLE_NEEDLES = (
    "connection refused",
    "max retries exceeded",
    "timed out",
    "temporary failure in name resolution",
)


def _looks_unreachable(exc: Exception, lowered_message: str) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return any(needle in lowered_message for needle in _UNREACHABLE_NEEDLES)


def _detail_for(
    category: AgentProvisioningErrorCategory,
    *,
    message: str,
    exc: Exception,
) -> str | None:
    if category is AgentProvisioningErrorCategory.QUOTA_EXHAUSTED:
        detail = _quota_detail(message)
    elif category is AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED:
        detail = _rbac_detail(message)
    elif category is AgentProvisioningErrorCategory.UNKNOWN:
        # Only the unclassified case falls back to the exception's class name. It
        # cannot carry a credential, and it is the one clue left once raw text is
        # dropped; on a classified failure the summary already says more than it would.
        detail = _exception_name(exc)
    else:
        detail = None
    return _bounded_safe_detail(detail)


def _quota_detail(message: str) -> str | None:
    """Rebuild which axis ran out and where it stands, from validated fragments.

    The axis is the diagnosis. requests.storage and limits.memory need different
    fixes, so it is extracted instead of dropped with the rest of the message.
    """
    axes: dict[str, dict[str, str]] = {}
    order: list[str] = []
    keyword: str | None = None
    for match in _QUOTA_PAIR.finditer(message):
        keyword = match.group(1) or keyword
        if keyword is None:
            continue
        axis, quantity = match.group(2), match.group(3)
        if axis not in axes:
            if len(order) >= _MAX_REPORTED_QUOTA_AXES:
                continue
            axes[axis] = {}
            order.append(axis)
        axes[axis][keyword] = quantity

    parts: list[str] = []
    for axis in order:
        measured = [f"{label} {axes[axis][key]}" for key, label in _QUOTA_KEYWORD_LABELS if key in axes[axis]]
        if measured:
            parts.append(f"{axis}: {', '.join(measured)}")
    if not parts:
        return None

    detail = "; ".join(parts)
    quota_name = _quota_name(message)
    resource_kind = _resource_kind(message)
    scope: list[str] = []
    if quota_name:
        scope.append(f"quota {quota_name}")
    if resource_kind:
        scope.append(f"creating {resource_kind}")
    return f"{detail} ({', '.join(scope)})" if scope else detail


def _quota_name(message: str) -> str | None:
    match = _QUOTA_NAME.search(message)
    return match.group(1) if match else None


def _resource_kind(message: str) -> str | None:
    match = _RESOURCE_KIND.match(message)
    return match.group(1) if match else None


def _rbac_detail(message: str) -> str | None:
    """The denied verb and resource kind, which is what an operator needs to grant.

    The service account name is left out. It is not needed to fix the RoleBinding.
    """
    match = _RBAC_RESOURCE.search(message)
    if match:
        return f"cannot {match.group(1)} {match.group(2)}"
    kind = _resource_kind(message)
    return f"creating {kind}" if kind else None


def _exception_name(exc: Exception) -> str | None:
    name = type(exc).__name__
    return name if _EXCEPTION_NAME.fullmatch(name) else None


def _bounded_safe_detail(detail: str | None) -> str | None:
    """Last check before a detail leaves this module.

    The extraction above is an allowlist, so this rarely fires. It guards against a
    future pattern that widens far enough to capture a credential.

    It also drops details that are safe. `count/secrets` is a real ResourceQuota
    axis, so exhausting it reports only that quota ran out. The full cluster text is
    in the logs.
    """
    if not detail:
        return None
    if _contains_sensitive(detail):
        return None
    return detail[:MAX_PROVISIONING_DETAIL_CHARS]


def _contains_sensitive(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)
