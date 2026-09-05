"""Provider error classification and API-safe messages."""

from __future__ import annotations

import socket
import ssl
from json import JSONDecodeError

import httpx

from homelab_monitor.models import ErrorCategory, ProviderError


class MalformedResponseError(ValueError):
    """Raised when an upstream response does not match its expected shape."""


_SAFE_MESSAGES = {
    ErrorCategory.TIMEOUT: "The provider timed out.",
    ErrorCategory.TLS: "The provider's TLS certificate could not be verified.",
    ErrorCategory.AUTHENTICATION: "The provider rejected its credentials.",
    ErrorCategory.DNS: "The provider hostname could not be resolved.",
    ErrorCategory.CONNECTION: "The provider could not be reached.",
    ErrorCategory.MALFORMED_RESPONSE: "The provider returned an invalid response.",
    ErrorCategory.UNEXPECTED: "The provider probe failed unexpectedly.",
}


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def classify_provider_error(exc: BaseException) -> ProviderError:
    """Return a stable category and sanitized message for an upstream failure."""
    chain = _exception_chain(exc)
    if any(isinstance(item, (ssl.SSLError, ssl.CertificateError)) for item in chain):
        category = ErrorCategory.TLS
    elif any(isinstance(item, socket.gaierror) for item in chain):
        category = ErrorCategory.DNS
    elif isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        category = ErrorCategory.TIMEOUT
    elif isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        category = ErrorCategory.AUTHENTICATION
    elif isinstance(
        exc,
        (
            MalformedResponseError,
            JSONDecodeError,
            httpx.DecodingError,
            KeyError,
            TypeError,
            ValueError,
        ),
    ):
        category = ErrorCategory.MALFORMED_RESPONSE
    elif isinstance(exc, (httpx.ConnectError, ConnectionError, OSError)):
        category = ErrorCategory.CONNECTION
    else:
        category = ErrorCategory.UNEXPECTED
    return ProviderError(category=category, message=_SAFE_MESSAGES[category])
