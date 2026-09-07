from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from homelab_monitor.errors import MalformedResponseError
from homelab_monitor.models import Freshness, Status
from homelab_monitor.providers.host_metrics import HostMetricsClient, normalize_host_metrics


def _thresholds() -> dict[str, dict[str, Any]]:
    return {
        "disk_used_percent": {
            "direction": "above",
            "warning": 80,
            "critical": 90,
            "sustained_samples": 1,
        },
        "temperature_c": {
            "direction": "above",
            "warning": 70,
            "critical": 85,
            "sustained_samples": 1,
        },
        "backup_age_hours": {
            "direction": "above",
            "warning": 24,
            "critical": 48,
            "sustained_samples": 1,
        },
        "cpu_used_percent": {
            "direction": "above",
            "warning": 85,
            "critical": 95,
            "sustained_samples": 3,
        },
        "memory_used_percent": {
            "direction": "above",
            "warning": 85,
            "critical": 95,
            "sustained_samples": 3,
        },
    }


def _payload() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "observed_at": "2026-09-05T18:00:00Z",
        "boot_id": "boot-2",
        "disks": [{"id": "root", "label": "Root", "used_percent": 92}],
        "temperatures": [{"id": "cpu", "label": "CPU package", "celsius": 75.5}],
        "smart": [
            {"id": "nvme0", "label": "System NVMe", "status": "passed"},
            {"id": "sda", "label": "Array disk", "status": "failed"},
        ],
        "backups": [
            {
                "id": "restic",
                "label": "Restic",
                "last_success_at": "2026-09-03T16:00:00Z",
            }
        ],
        "cpu": {"used_percent": 86},
        "memory": {"used_percent": 52.25},
    }


def test_normalizes_host_metrics_and_explicit_thresholds() -> None:
    result = normalize_host_metrics(
        _payload(),
        _thresholds(),
        now=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    )
    measurements = {item.id: item for item in result.measurements}

    assert result.status == Status.UNAVAILABLE
    assert result.boot_id == "boot-2"
    assert result.observed_at == "2026-09-05T18:00:00.000+00:00"
    assert measurements["disk:root:used_percent"].status == Status.UNAVAILABLE
    assert measurements["temperature:cpu"].status == Status.DEGRADED
    assert measurements["smart:nvme0"].status == Status.HEALTHY
    assert measurements["smart:sda"].status == Status.UNAVAILABLE
    assert measurements["backup:restic:age"].value == 50
    assert measurements["cpu:used_percent"].status == Status.DEGRADED
    assert measurements["cpu:used_percent"].thresholds is not None
    assert measurements["cpu:used_percent"].thresholds.sustained_samples == 3
    assert measurements["memory:used_percent"].status == Status.HEALTHY
    assert measurements["system:boot_id"].status == Status.UNKNOWN


def test_missing_optional_metrics_are_explicitly_unknown() -> None:
    result = normalize_host_metrics(
        {
            "schema_version": "1",
            "observed_at": "2026-09-05T18:00:00+00:00",
        },
        _thresholds(),
        now=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    )

    assert result.status == Status.UNKNOWN
    assert result.boot_id is None
    assert len(result.measurements) == 7
    assert all(item.status == Status.UNKNOWN for item in result.measurements)
    assert all(item.freshness == Freshness.UNKNOWN for item in result.measurements)
    assert all(item.thresholds is not None for item in result.measurements)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"extra": True}), "unsupported fields"),
        (lambda payload: payload.update({"schema_version": "2"}), "schema_version"),
        (
            lambda payload: payload.update(
                {"disks": [{"id": "root", "used_percent": "nearly full"}]}
            ),
            "must be numeric",
        ),
        (
            lambda payload: payload.update({"cpu": {"used_percent": 101}}),
            "supported range",
        ),
        (
            lambda payload: payload.update({"observed_at": "2026-09-05T18:00:00"}),
            "include a timezone",
        ),
    ],
)
def test_rejects_malformed_host_metrics_payloads(mutation: Any, message: str) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(MalformedResponseError, match=message):
        normalize_host_metrics(
            payload,
            _thresholds(),
            now=datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
        )


def test_https_client_uses_optional_bearer_token_without_exposing_it() -> None:
    token = "metrics-secret-value"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(200, json=_payload())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = HostMetricsClient(
        {
            "url": "https://metrics.example.test/v1/metrics",
            "api_key": token,
            "verify_tls": True,
            "thresholds": _thresholds(),
        },
        timeout=1,
        client=client,
    ).collect(now=datetime(2026, 9, 5, 18, 0, tzinfo=UTC))

    assert result.probe_duration_ms is not None
    assert result.probe_duration_ms >= 1

    malformed_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"schema_version": "1", "observed_at": "invalid"},
            )
        )
    )
    with pytest.raises(MalformedResponseError) as raised:
        HostMetricsClient(
            {
                "url": "https://metrics.example.test/v1/metrics",
                "api_key": token,
                "verify_tls": True,
                "thresholds": _thresholds(),
            },
            timeout=1,
            client=malformed_client,
        ).collect()
    assert token not in str(raised.value)


def test_host_metrics_client_rejects_non_https_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HostMetricsClient(
            {
                "url": "http://metrics.example.test/v1/metrics",
                "thresholds": _thresholds(),
            },
            timeout=1,
        )
