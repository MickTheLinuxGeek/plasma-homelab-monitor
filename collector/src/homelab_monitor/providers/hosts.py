"""Generic HTTP and TCP host probes."""

from __future__ import annotations

import socket
from time import monotonic
from typing import Any

import httpx

from homelab_monitor.models import HostStatus, Status
from homelab_monitor.tls import tls_verification


def _elapsed_ms(started: float) -> int:
    return max(1, round((monotonic() - started) * 1000))


def probe_host(host: dict[str, Any], timeout: float) -> HostStatus:
    """Probe one configured host without requiring an agent on that host."""
    host_id = str(host.get("id") or host.get("name") or "host")
    name = str(host.get("name") or host_id)
    dashboard_url = host.get("dashboard_url")
    probe = host.get("probe") or {}
    probe_type = probe.get("type")
    started = monotonic()

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
        status=Status.HEALTHY,
        detail=detail,
        dashboard_url=dashboard_url,
        latency_ms=_elapsed_ms(started),
    )
