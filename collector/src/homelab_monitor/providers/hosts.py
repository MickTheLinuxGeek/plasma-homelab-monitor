"""Generic HTTP and TCP host probes."""

from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx

from homelab_monitor.models import HostStatus, Status
from homelab_monitor.tls import tls_verification


def _elapsed_ms(started: float) -> int:
    return max(1, round((monotonic() - started) * 1000))


def verified_certificate_expiry(
    url: str,
    tls_config: dict[str, Any],
    timeout: float,
    *,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Return verified HTTPS certificate expiration and whole days remaining."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("certificate expiry requires an HTTPS URL with a hostname")
    verification = tls_verification(tls_config)
    if verification is False:
        raise ValueError("certificate expiry requires TLS verification")
    if isinstance(verification, ssl.SSLContext):
        context = verification
    else:
        context = ssl.create_default_context()
    port = parsed.port or 443
    with (
        socket.create_connection((parsed.hostname, port), timeout=timeout) as connection,
        context.wrap_socket(connection, server_hostname=parsed.hostname) as tls_socket,
    ):
        certificate = tls_socket.getpeercert()
    not_after = certificate.get("notAfter")
    if not isinstance(not_after, str):
        raise ssl.CertificateError("verified certificate omitted its expiration")
    expires_at = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=UTC)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    days_remaining = int((expires_at - current).total_seconds() // 86400)
    return expires_at.isoformat(timespec="milliseconds"), days_remaining


def _certificate_status(days_remaining: int, config: dict[str, Any]) -> Status:
    thresholds = config.get("certificate_thresholds")
    if not isinstance(thresholds, dict):
        return Status.HEALTHY
    warning = float(thresholds["warning"])
    critical = float(thresholds["critical"])
    if days_remaining <= critical or days_remaining <= warning:
        return Status.DEGRADED
    return Status.HEALTHY


def probe_host(host: dict[str, Any], timeout: float) -> HostStatus:
    """Probe one configured host without requiring an agent on that host."""
    host_id = str(host.get("id") or host.get("name") or "host")
    name = str(host.get("name") or host_id)
    dashboard_url = host.get("dashboard_url")
    probe = host.get("probe") or {}
    probe_type = probe.get("type")
    started = monotonic()
    certificate_expires_at: str | None = None
    certificate_days_remaining: int | None = None
    status = Status.HEALTHY

    if probe_type == "http":
        url = str(probe["url"])
        with httpx.Client(
            timeout=timeout,
            verify=tls_verification(probe),
            follow_redirects=True,
        ) as client:
            response = client.get(url)
        response.raise_for_status()
        detail = f"HTTP {response.status_code}"
        if urlsplit(url).scheme == "https" and bool(probe.get("verify_tls", True)):
            certificate_expires_at, certificate_days_remaining = verified_certificate_expiry(
                url,
                probe,
                timeout,
            )
            status = _certificate_status(certificate_days_remaining, host)
            if status != Status.HEALTHY:
                detail = f"{detail}; certificate expires in {certificate_days_remaining} days"
    elif probe_type == "tcp":
        target = str(probe["host"])
        port = int(probe["port"])
        with socket.create_connection((target, port), timeout=timeout):
            pass
        detail = f"TCP {target}:{port}"
    else:
        raise ValueError("probe.type must be 'http' or 'tcp'")

    return HostStatus(
        id=host_id,
        name=name,
        status=status,
        detail=detail,
        dashboard_url=dashboard_url,
        latency_ms=_elapsed_ms(started),
        certificate_expires_at=certificate_expires_at,
        certificate_days_remaining=certificate_days_remaining,
    )
