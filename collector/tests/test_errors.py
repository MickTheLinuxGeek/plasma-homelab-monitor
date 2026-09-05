import socket
import ssl

import httpx
import pytest
from homelab_monitor.errors import MalformedResponseError, classify_provider_error
from homelab_monitor.models import ErrorCategory


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.example.test")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("raw provider response", request=request, response=response)


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (httpx.ReadTimeout("private timeout detail"), ErrorCategory.TIMEOUT),
        (_http_status_error(401), ErrorCategory.AUTHENTICATION),
        (MalformedResponseError("private payload detail"), ErrorCategory.MALFORMED_RESPONSE),
        (RuntimeError("private unexpected detail"), ErrorCategory.UNEXPECTED),
    ],
)
def test_provider_errors_are_classified_and_sanitized(
    error: BaseException,
    category: ErrorCategory,
) -> None:
    result = classify_provider_error(error)

    assert result.category == category
    assert "private" not in result.message


def test_nested_dns_error_is_classified() -> None:
    error = httpx.ConnectError("private DNS detail")
    error.__cause__ = socket.gaierror("private hostname")

    assert classify_provider_error(error).category == ErrorCategory.DNS


def test_nested_certificate_error_is_classified() -> None:
    error = httpx.ConnectError("private TLS detail")
    error.__cause__ = ssl.SSLCertVerificationError("private certificate")

    assert classify_provider_error(error).category == ErrorCategory.TLS
