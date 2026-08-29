"""Safe, structured diagnostics for Communication provider failures."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError

from api.domains.communications.models import CommunicationErrorCategory, CommunicationErrorDetails

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_SAFE_OPERATION = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)
_REDACTED_ERROR_CODE = "REDACTED"
_REDACTED_ERROR_SUMMARY = "Provider error details were redacted"
_SAFE_ERROR_SUMMARIES = {
    "agent was not running when the message arrived": "Agent was not running when the message arrived",
    "communication connection is unavailable": "Communication Connection is unavailable",
    "communication connection was retired": "Communication Connection was retired",
    _REDACTED_ERROR_SUMMARY.casefold(): _REDACTED_ERROR_SUMMARY,
}
_ERROR_CODES = {
    CommunicationErrorCategory.AUTHENTICATION: "AUTHENTICATION_FAILED",
    CommunicationErrorCategory.AUTHORIZATION: "AUTHORIZATION_FAILED",
    CommunicationErrorCategory.CONFIGURATION: "CONFIGURATION_ERROR",
    CommunicationErrorCategory.NETWORK: "NETWORK_ERROR",
    CommunicationErrorCategory.PROVIDER_REJECTED: "PROVIDER_REJECTED",
    CommunicationErrorCategory.PROVIDER_UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    CommunicationErrorCategory.RATE_LIMITED: "RATE_LIMITED",
    CommunicationErrorCategory.TIMEOUT: "TIMEOUT",
    CommunicationErrorCategory.UNKNOWN: "PROVIDER_ERROR",
}
_SUMMARY_BY_CATEGORY = {
    CommunicationErrorCategory.AUTHENTICATION: "Provider rejected the connection credential",
    CommunicationErrorCategory.AUTHORIZATION: "Provider denied the requested operation",
    CommunicationErrorCategory.CONFIGURATION: "The connection configuration is invalid",
    CommunicationErrorCategory.NETWORK: "The connection to the provider could not be established",
    CommunicationErrorCategory.PROVIDER_REJECTED: "The provider rejected the request",
    CommunicationErrorCategory.PROVIDER_UNAVAILABLE: "The provider is temporarily unavailable",
    CommunicationErrorCategory.RATE_LIMITED: "The provider rate-limited the request",
    CommunicationErrorCategory.TIMEOUT: "The provider did not respond before the request timed out",
    CommunicationErrorCategory.UNKNOWN: "The provider reported an error",
}
_HTTP_PROVIDER_CODE_KEYS = ("error", "code", "error_code", "type")
_REQUEST_ID_HEADERS = ("x-request-id", "x-correlation-id", "request-id", "x-slack-req-id", "cf-ray")
_CODE_SUFFIX = re.compile(
    r"(?:error|failed|code|reason)\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9_.:-]{0,99})\s*$",
    re.IGNORECASE,
)
_COMMON_EXCEPTION_NAMES = {
    "ConnectError",
    "HTTPStatusError",
    "KeyError",
    "RuntimeError",
    "TimeoutError",
    "TimeoutException",
    "ValueError",
}


@dataclass(frozen=True)
class NormalizedCommunicationError:
    """The only error representation allowed to cross into persistence."""

    code: str | None
    summary: str | None
    details: CommunicationErrorDetails | None


def normalize_communication_error(
    error: BaseException | None = None,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
    operation: str | None = None,
) -> NormalizedCommunicationError:
    """Extract useful bounded diagnostics without retaining exception text.

    The exception and its message are inspected only in memory. Provider
    response bodies are used solely to extract a validated error identifier;
    free-form provider text never enters the returned object.
    """
    if error is None and error_code is None and error_message is None:
        return NormalizedCommunicationError(code=None, summary=None, details=None)

    if error_code is not None and _contains_sensitive(error_code):
        return NormalizedCommunicationError(
            code=_REDACTED_ERROR_CODE,
            summary=_REDACTED_ERROR_SUMMARY,
            details=None,
        )

    raw_code = error_code or (type(error).__name__ if error is not None else None)
    raw_message = error_message if error_message is not None else (str(error) if error is not None else "")
    http_status, provider_code, retry_after_seconds, request_id = _http_metadata(error)
    if provider_code is None:
        provider_code = _safe_identifier(_provider_code_from_message(raw_message))

    category = _classify_error(
        error,
        code=raw_code,
        message=raw_message,
        http_status=http_status,
    )
    details = CommunicationErrorDetails(
        category=category,
        operation=_safe_operation(operation),
        http_status=http_status,
        provider_code=provider_code,
        retryable=_is_retryable(category, http_status),
        retry_after_seconds=retry_after_seconds,
        request_id=request_id,
    )
    code = _error_code_for(raw_code, error=error, category=category)
    return NormalizedCommunicationError(
        code=code,
        summary=error_summary_from_details(details),
        details=details,
    )


def safe_error_code(value: str | None) -> str | None:
    if not value:
        return None
    if _contains_sensitive(value) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        return _REDACTED_ERROR_CODE
    return value


def safe_error_details(value: CommunicationErrorDetails | Mapping[str, Any] | None) -> CommunicationErrorDetails | None:
    if value is None:
        return None
    try:
        return (
            value if isinstance(value, CommunicationErrorDetails) else CommunicationErrorDetails.model_validate(value)
        )
    except TypeError, ValueError, ValidationError:
        return None


def error_code_from_details(details: CommunicationErrorDetails | Mapping[str, Any] | None) -> str | None:
    safe_details = safe_error_details(details)
    return _ERROR_CODES[safe_details.category] if safe_details is not None else None


def error_summary_from_details(details: CommunicationErrorDetails | Mapping[str, Any]) -> str:
    safe_details = safe_error_details(details)
    if safe_details is None:
        return _REDACTED_ERROR_SUMMARY
    summary = _SUMMARY_BY_CATEGORY[safe_details.category]
    qualifiers: list[str] = []
    if safe_details.http_status is not None:
        qualifiers.append(f"HTTP {safe_details.http_status}")
    if safe_details.provider_code is not None:
        qualifiers.append(safe_details.provider_code)
    return f"{summary} ({', '.join(qualifiers)})" if qualifiers else summary


def safe_error_summary(
    value: str | None,
    *,
    details: CommunicationErrorDetails | Mapping[str, Any] | None = None,
) -> str | None:
    safe_details = safe_error_details(details)
    if safe_details is not None:
        return error_summary_from_details(safe_details)
    if not value:
        return None
    normalized = " ".join(value.split())
    return _SAFE_ERROR_SUMMARIES.get(normalized.casefold(), _REDACTED_ERROR_SUMMARY)


def _http_metadata(
    error: BaseException | None,
) -> tuple[int | None, str | None, int | None, str | None]:
    if not isinstance(error, httpx.HTTPStatusError):
        return None, None, None, None
    response = error.response
    provider_code = None
    try:
        body = response.json()
    except TypeError, ValueError:
        body = None
    if isinstance(body, dict):
        for key in _HTTP_PROVIDER_CODE_KEYS:
            candidate = body.get(key)
            if isinstance(candidate, (str, int)):
                provider_code = _safe_identifier(str(candidate))
                if provider_code is not None:
                    break
    retry_after = _bounded_integer(response.headers.get("retry-after"))
    request_id = next(
        (
            candidate
            for header in _REQUEST_ID_HEADERS
            if (candidate := _safe_request_id(response.headers.get(header))) is not None
        ),
        None,
    )
    return response.status_code, provider_code, retry_after, request_id


def _classify_error(
    error: BaseException | None,
    *,
    code: str | None,
    message: str,
    http_status: int | None,
) -> CommunicationErrorCategory:
    if http_status == 401:
        return CommunicationErrorCategory.AUTHENTICATION
    if http_status == 403:
        return CommunicationErrorCategory.AUTHORIZATION
    if http_status == 408:
        return CommunicationErrorCategory.TIMEOUT
    if http_status == 429:
        return CommunicationErrorCategory.RATE_LIMITED
    if http_status is not None and http_status >= 500:
        return CommunicationErrorCategory.PROVIDER_UNAVAILABLE
    if http_status is not None and 400 <= http_status < 500:
        return CommunicationErrorCategory.PROVIDER_REJECTED

    normalized = f"{code or ''} {message}".casefold()
    if isinstance(error, (httpx.TimeoutException, TimeoutError)) or _contains_any(
        normalized, "timeout", "timed out", "deadline exceeded"
    ):
        return CommunicationErrorCategory.TIMEOUT
    if isinstance(error, PermissionError) or _contains_any(
        normalized, "forbidden", "permission denied", "access denied", "not authorized"
    ):
        return CommunicationErrorCategory.AUTHORIZATION
    if _contains_any(normalized, "invalid_auth", "unauthorized", "invalid credential", "credential rejected"):
        return CommunicationErrorCategory.AUTHENTICATION
    if _contains_any(normalized, "rate_limit", "rate limited", "too many requests", "throttl"):
        return CommunicationErrorCategory.RATE_LIMITED
    if isinstance(error, (httpx.TransportError, ConnectionError)) or _contains_any(
        normalized, "network", "connecterror", "connection refused", "dns", "socket", "transport"
    ):
        return CommunicationErrorCategory.NETWORK
    if isinstance(error, (KeyError, NotImplementedError)) or _contains_any(
        normalized, "configuration", "unsupported", "not supervised", "missing setting"
    ):
        return CommunicationErrorCategory.CONFIGURATION
    if _contains_any(normalized, "unavailable", "server error", "bad gateway", "service unavailable"):
        return CommunicationErrorCategory.PROVIDER_UNAVAILABLE
    return CommunicationErrorCategory.UNKNOWN


def _error_code_for(
    raw_code: str | None,
    *,
    error: BaseException | None,
    category: CommunicationErrorCategory,
) -> str:
    safe_code = safe_error_code(raw_code)
    if safe_code not in (None, _REDACTED_ERROR_CODE) and (error is None or raw_code != type(error).__name__):
        return safe_code
    return _ERROR_CODES[category]


def _is_retryable(category: CommunicationErrorCategory, http_status: int | None) -> bool:
    if http_status in {401, 403}:
        return False
    return category in {
        CommunicationErrorCategory.NETWORK,
        CommunicationErrorCategory.PROVIDER_UNAVAILABLE,
        CommunicationErrorCategory.RATE_LIMITED,
        CommunicationErrorCategory.TIMEOUT,
    }


def _provider_code_from_message(value: str) -> str | None:
    match = _CODE_SUFFIX.search(value)
    if match is None:
        return None
    return match.group(1)


def _safe_identifier(value: str | None) -> str | None:
    if value is None or _contains_sensitive(value) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        return None
    return value


def _safe_request_id(value: str | None) -> str | None:
    if value is None or len(value) > 128 or _contains_sensitive(value):
        return None
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else None


def _safe_operation(value: str | None) -> str:
    return value if value is not None and _SAFE_OPERATION.fullmatch(value) is not None else "unknown"


def _bounded_integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if 0 <= parsed <= 86_400 else None


def _contains_sensitive(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _contains_any(value: str, *needles: str) -> bool:
    return any(needle in value for needle in needles)
