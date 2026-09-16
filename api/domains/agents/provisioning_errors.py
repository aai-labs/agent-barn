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
    LIMIT_EXCEEDED = "limit_exceeded"
    CLUSTER_PERMISSION_DENIED = "cluster_permission_denied"
    RESOURCE_REJECTED = "resource_rejected"
    NAMESPACE_MISSING = "namespace_missing"
    CLUSTER_UNAVAILABLE = "cluster_unavailable"
    UNKNOWN = "unknown"


class AgentProvisioningOperation(str, enum.Enum):
    """What the caller was doing. Only the opening clause of the copy differs."""

    START = "start"
    BACKUP = "backup"
    RESTORE = "restore"


_LEAD_BY_OPERATION: dict[AgentProvisioningOperation, str] = {
    AgentProvisioningOperation.START: "The agent could not start",
    AgentProvisioningOperation.BACKUP: "The backup could not be created",
    AgentProvisioningOperation.RESTORE: "The restore could not be completed",
}


_ERROR_CODES: dict[AgentProvisioningErrorCategory, str] = {
    AgentProvisioningErrorCategory.QUOTA_EXHAUSTED: "QUOTA_EXHAUSTED",
    AgentProvisioningErrorCategory.LIMIT_EXCEEDED: "LIMIT_EXCEEDED",
    AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED: "CLUSTER_PERMISSION_DENIED",
    AgentProvisioningErrorCategory.RESOURCE_REJECTED: "RESOURCE_REJECTED",
    AgentProvisioningErrorCategory.NAMESPACE_MISSING: "NAMESPACE_MISSING",
    AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE: "CLUSTER_UNAVAILABLE",
    AgentProvisioningErrorCategory.UNKNOWN: "PROVISIONING_FAILED",
}

_CATEGORY_BY_CODE: dict[str, AgentProvisioningErrorCategory] = {
    code: category for category, code in _ERROR_CODES.items()
}

_CONDITION_BY_CATEGORY: dict[AgentProvisioningErrorCategory, str] = {
    AgentProvisioningErrorCategory.QUOTA_EXHAUSTED: (
        "its namespace has run out of resource quota. Ask an administrator to free up or raise it."
    ),
    AgentProvisioningErrorCategory.LIMIT_EXCEEDED: (
        "the request is larger than the namespace allows for a single resource. "
        "Ask an administrator to review the namespace limits."
    ),
    AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED: (
        "Agent Barn's service account is missing RBAC permission to create the resources. "
        "Ask an administrator to review them."
    ),
    AgentProvisioningErrorCategory.RESOURCE_REJECTED: (
        "the cluster rejected the resource definition as invalid. "
        "Ask an administrator to review the agent's runtime configuration."
    ),
    AgentProvisioningErrorCategory.NAMESPACE_MISSING: (
        "its Kubernetes namespace does not exist. Ask an administrator to check the cluster setup."
    ),
    AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE: (
        "the Kubernetes API could not be reached. This is often temporary, so try again in a moment."
    ),
    AgentProvisioningErrorCategory.UNKNOWN: (
        "creating the Kubernetes resources failed unexpectedly. "
        "Try again; if it keeps failing, ask an administrator to check the cluster."
    ),
}

# Only fixed resource names are safe to expose. Custom resource/quota names and
# unfamiliar formats keep the category summary without a detail.
_RESOURCE = r"(?:pods|persistentvolumeclaims|services|configmaps|deployments|replicasets|statefulsets|daemonsets|jobs|cronjobs|replicationcontrollers|resourcequotas)"
# Quota axes for non-core API groups carry the group: count/deployments.apps.
_COUNTED = rf"{_RESOURCE}(?:\.(?:apps|batch))?"
_AXIS = rf"(?:requests\.(?:storage|cpu|memory|ephemeral-storage)|limits\.(?:cpu|memory|ephemeral-storage)|cpu|memory|services\.(?:nodeports|loadbalancers)|{_RESOURCE}|count/{_COUNTED})"
_QUANTITY = r"[0-9]{1,18}(?:\.[0-9]{1,9})?(?:[EPTGMK]i|[numkKMGTPE]|[eE][+-]?[0-9]{1,3})?"
_PAIR = rf"{_AXIS}={_QUANTITY}"
_QUOTA_SECTION = re.compile(
    rf"exceeded quota: [^,\r\n]{{1,253}}, requested: (?P<requested>{_PAIR}(?:,\s*{_PAIR})*), "
    rf"used: (?P<used>{_PAIR}(?:,\s*{_PAIR})*), limited: (?P<limited>{_PAIR}(?:,\s*{_PAIR})*)\Z"
)
_QUOTA_PAIR = re.compile(rf"({_AXIS})=({_QUANTITY})")
_QUOTA_ROW = rf"{_AXIS}: requested {_QUANTITY}, used {_QUANTITY}, limit {_QUANTITY}"
_STORED_QUOTA = re.compile(rf"{_QUOTA_ROW}(?:; {_QUOTA_ROW}){{0,2}}")
_RESOURCE_KIND = re.compile(rf'^({_RESOURCE})\s+"')
# A LimitRange rejection names the constrained axis, the scope it applies to, the
# limit and the request. Every part is a fixed word or a Kubernetes quantity.
_LIMIT_AXIS = r"(?:storage|cpu|memory|ephemeral-storage)"
_LIMIT_SCOPE = r"(?:PersistentVolumeClaim|Container|Pod)"
_LIMIT_RANGE = re.compile(
    rf"(maximum|minimum) ({_LIMIT_AXIS}) usage per ({_LIMIT_SCOPE}) is ({_QUANTITY}), "
    rf"but (?:request|limit) is ({_QUANTITY})"
)
_STORED_LIMIT = re.compile(rf"{_LIMIT_AXIS} per {_LIMIT_SCOPE}: requested {_QUANTITY}, (?:maximum|minimum) {_QUANTITY}")
_VERB = r"(?:create|get|update|delete|list|watch|patch)"
_RBAC_RESOURCE = re.compile(rf'cannot\s+({_VERB})\s+resource\s+"({_RESOURCE})"')
_STORED_RBAC = re.compile(rf"(?:cannot {_VERB} {_RESOURCE}|creating {_RESOURCE})")
_EXCEPTION_NAMES = frozenset({"ValueError", "RuntimeError", "TypeError", "KeyError", "ApiException"})
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


def normalize_agent_provisioning_error(
    exc: Exception,
    *,
    operation: AgentProvisioningOperation = AgentProvisioningOperation.START,
) -> NormalizedAgentProvisioningError:
    """Classify a provisioning failure and rebuild a safe, bounded detail for it."""
    status_code = _status_code_of(exc)
    message = _cluster_message(exc)
    category = _classify(exc, status_code=status_code, message=message)
    return _for_category(
        category,
        detail=_detail_for(category, message=message or "", exc=exc),
        operation=operation,
    )


def persisted_provisioning_error(
    *,
    code: str | None,
    detail: str | None,
    legacy_message: str | None,
) -> NormalizedAgentProvisioningError | None:
    """Rebuild a stored failure at the read boundary.

    The code selects fixed copy and the detail must match its category grammar,
    so improved copy reaches Agents already sitting in ERROR without a data migration.

    A row with no code but a message was written before normalization existed. Its
    text came straight from the cluster, so it is reported as an unclassified
    failure and the stored text is dropped.
    """
    if code is None:
        return _for_category(AgentProvisioningErrorCategory.UNKNOWN, detail=None) if legacy_message else None
    category = _CATEGORY_BY_CODE.get(code, AgentProvisioningErrorCategory.UNKNOWN)
    return _for_category(category, detail=_bounded_safe_detail(detail, category))


def _for_category(
    category: AgentProvisioningErrorCategory,
    *,
    detail: str | None,
    operation: AgentProvisioningOperation = AgentProvisioningOperation.START,
) -> NormalizedAgentProvisioningError:
    return NormalizedAgentProvisioningError(
        code=_ERROR_CODES[category],
        category=category,
        summary=f"{_LEAD_BY_OPERATION[operation]} — {_CONDITION_BY_CATEGORY[category]}",
        detail=detail,
    )


def _status_code_of(exc: Exception) -> int | None:
    status_code = getattr(exc, "status", None)
    return status_code if isinstance(status_code, int) else None


def _cluster_message(exc: Exception) -> str | None:
    """The cluster's own message, or None when the Kubernetes API did not answer.

    Used only for classification and pattern extraction, never returned to a
    caller. ``ApiException.body`` is a JSON Status object.
    """
    body: Any = getattr(exc, "body", None)
    if not body:
        return None
    try:
        parsed = json.loads(body) if isinstance(body, (str, bytes)) else body
    except TypeError, ValueError:
        parsed = None
    if isinstance(parsed, dict):
        message = parsed.get("message") or parsed.get("reason")
        if isinstance(message, str) and message:
            return message
    return body if isinstance(body, str) else None


def _classify(
    exc: Exception,
    *,
    status_code: int | None,
    message: str | None,
) -> AgentProvisioningErrorCategory:
    # Everything below matches wording the Kubernetes API uses. An exception from
    # anywhere else in provisioning carries unrelated text, and a RuntimeError
    # saying "skill version not found" is not the namespace being unreachable.
    if message is None and status_code is None:
        if _looks_unreachable(exc):
            return AgentProvisioningErrorCategory.CLUSTER_UNAVAILABLE
        return AgentProvisioningErrorCategory.UNKNOWN

    lowered = (message or "").casefold()

    # A full ResourceQuota and a missing RoleBinding both come back as 403 Forbidden.
    # Reporting quota exhaustion as an RBAC fault sends operators to the service
    # account when the namespace has simply run out of a resource, so quota wins.
    if "exceeded quota" in lowered:
        return AgentProvisioningErrorCategory.QUOTA_EXHAUSTED
    # A LimitRange rejection is also a 403 "forbidden", but the fix is the namespace's
    # per-object limits, not a RoleBinding.
    if " usage per " in lowered:
        return AgentProvisioningErrorCategory.LIMIT_EXCEEDED
    if status_code == 403 or "forbidden" in lowered or "cannot create resource" in lowered:
        return AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED
    if status_code == 422 or "is invalid" in lowered or "unprocessable" in lowered:
        return AgentProvisioningErrorCategory.RESOURCE_REJECTED
    # A 404 is the API server answering that something is absent. It does not come
    # back on its own, so it must not be described as a temporary outage.
    if status_code == 404 or "not found" in lowered:
        return AgentProvisioningErrorCategory.NAMESPACE_MISSING
    # A 5xx means the API server answered, so the namespace is reachable.
    return AgentProvisioningErrorCategory.UNKNOWN


_UNREACHABLE_NEEDLES = (
    "connection refused",
    "max retries exceeded",
    "timed out",
    "temporary failure in name resolution",
)

# Transport failures reach us from the HTTP stack the Kubernetes client uses, so
# their text is safe to match. Application code raising the same words is not.
_TRANSPORT_MODULES = ("urllib3", "kubernetes", "http", "socket", "ssl", "httpx", "httpcore")


def _looks_unreachable(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if type(exc).__module__.split(".")[0] not in _TRANSPORT_MODULES:
        return False
    lowered = str(exc).casefold()
    return any(needle in lowered for needle in _UNREACHABLE_NEEDLES)


def _detail_for(
    category: AgentProvisioningErrorCategory,
    *,
    message: str,
    exc: Exception,
) -> str | None:
    if category is AgentProvisioningErrorCategory.QUOTA_EXHAUSTED:
        detail = _quota_detail(message)
    elif category is AgentProvisioningErrorCategory.LIMIT_EXCEEDED:
        detail = _limit_detail(message)
    elif category is AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED:
        detail = _rbac_detail(message)
    elif category is AgentProvisioningErrorCategory.UNKNOWN:
        # Only the unclassified case falls back to the exception's class name. It
        # comes from a fixed allowlist, and it is the one clue left once raw text is
        # dropped; on a classified failure the summary already says more than it would.
        detail = _exception_name(exc)
    else:
        detail = None
    return _bounded_safe_detail(detail, category)


def _quota_detail(message: str) -> str | None:
    """Rebuild which axis ran out and where it stands, from validated fragments.

    The axis is the diagnosis. requests.storage and limits.memory need different
    fixes, so it is extracted instead of dropped with the rest of the message.
    """
    section = _QUOTA_SECTION.search(message)
    if section is None:
        return None
    measurements = {key: dict(_QUOTA_PAIR.findall(section.group(key))) for key, _ in _QUOTA_KEYWORD_LABELS}
    axes = list(measurements["requested"])
    if any(set(values) != set(axes) for values in measurements.values()):
        return None
    return "; ".join(
        f"{axis}: " + ", ".join(f"{label} {measurements[key][axis]}" for key, label in _QUOTA_KEYWORD_LABELS)
        for axis in axes[:_MAX_REPORTED_QUOTA_AXES]
    )


def _limit_detail(message: str) -> str | None:
    """Which axis the namespace caps, and how far the request is over it."""
    match = _LIMIT_RANGE.search(message)
    if match is None:
        return None
    bound, axis, scope, limit, requested = match.groups()
    return f"{axis} per {scope}: requested {requested}, {bound} {limit}"


def _rbac_detail(message: str) -> str | None:
    """The denied verb and resource kind, which is what an operator needs to grant.

    The service account name is left out. It is not needed to fix the RoleBinding.
    """
    match = _RBAC_RESOURCE.search(message)
    if match:
        return f"cannot {match.group(1)} {match.group(2)}"
    match = _RESOURCE_KIND.match(message)
    kind = match.group(1) if match else None
    return f"creating {kind}" if kind else None


def _exception_name(exc: Exception) -> str | None:
    name = type(exc).__name__
    return name if name in _EXCEPTION_NAMES else None


def _bounded_safe_detail(detail: str | None, category: AgentProvisioningErrorCategory) -> str | None:
    """Reject details outside the category's complete grammar, including on reads."""
    if not detail or len(detail) > MAX_PROVISIONING_DETAIL_CHARS or _contains_sensitive(detail):
        return None
    if category is AgentProvisioningErrorCategory.QUOTA_EXHAUSTED:
        return detail if _STORED_QUOTA.fullmatch(detail) else None
    if category is AgentProvisioningErrorCategory.LIMIT_EXCEEDED:
        return detail if _STORED_LIMIT.fullmatch(detail) else None
    if category is AgentProvisioningErrorCategory.CLUSTER_PERMISSION_DENIED:
        return detail if _STORED_RBAC.fullmatch(detail) else None
    if category is AgentProvisioningErrorCategory.UNKNOWN:
        return detail if detail in _EXCEPTION_NAMES else None
    return None


def _contains_sensitive(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)
