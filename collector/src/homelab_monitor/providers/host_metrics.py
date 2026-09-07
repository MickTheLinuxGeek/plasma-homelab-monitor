"""Verified HTTPS host metrics collection and strict payload normalization."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

from homelab_monitor.errors import MalformedResponseError
from homelab_monitor.models import (
    Freshness,
    HostMetricsStatus,
    Measurement,
    Status,
    ThresholdDefinition,
    ThresholdDirection,
)
from homelab_monitor.tls import tls_verification

_PAYLOAD_KEYS = {
    "schema_version",
    "observed_at",
    "boot_id",
    "disks",
    "temperatures",
    "smart",
    "backups",
    "cpu",
    "memory",
}
_THRESHOLD_KINDS = {
    "disk_used_percent",
    "temperature_c",
    "backup_age_hours",
    "cpu_used_percent",
    "memory_used_percent",
}


def _malformed(message: str) -> MalformedResponseError:
    return MalformedResponseError(f"Host metrics payload {message}")


def _mapping(value: Any, path: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _malformed(f"{path} must be an object")
    extra = set(value) - allowed
    missing = required - set(value)
    if extra:
        raise _malformed(f"{path} contains unsupported fields")
    if missing:
        raise _malformed(f"{path} is missing required fields")
    return value


def _items(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _malformed(f"{path} must be an array")
    return value


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _malformed(f"{path} must be a non-empty string")
    return value.strip()


def _label(value: Any, default: str, path: str) -> str:
    if value is None:
        return default
    return _identifier(value, path)


def _number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _malformed(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise _malformed(f"{path} must be finite")
    if minimum is not None and number < minimum:
        raise _malformed(f"{path} is below the supported range")
    if maximum is not None and number > maximum:
        raise _malformed(f"{path} is above the supported range")
    return number


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise _malformed(f"{path} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _malformed(f"{path} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise _malformed(f"{path} must include a timezone")
    return parsed.astimezone(UTC)


def _timestamp_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


def _thresholds(config: dict[str, Any]) -> dict[str, ThresholdDefinition]:
    if not isinstance(config, dict) or set(config) != _THRESHOLD_KINDS:
        raise ValueError("host metrics thresholds must explicitly define every supported metric")
    normalized: dict[str, ThresholdDefinition] = {}
    for kind in sorted(_THRESHOLD_KINDS):
        raw = config[kind]
        if not isinstance(raw, dict):
            raise ValueError(f"host metrics threshold {kind} must be an object")
        try:
            direction = ThresholdDirection(str(raw["direction"]))
            warning = float(raw["warning"])
            critical = float(raw["critical"])
            sustained_samples = int(raw.get("sustained_samples", 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"host metrics threshold {kind} is invalid") from exc
        if direction == ThresholdDirection.CATEGORICAL:
            raise ValueError(f"host metrics threshold {kind} must be numeric")
        if not all(math.isfinite(value) and value >= 0 for value in (warning, critical)):
            raise ValueError(f"host metrics threshold {kind} must be finite and nonnegative")
        if sustained_samples < 1:
            raise ValueError(f"host metrics threshold {kind} sustained_samples must be positive")
        if direction == ThresholdDirection.ABOVE and critical < warning:
            raise ValueError(f"host metrics threshold {kind} critical must be at least warning")
        if direction == ThresholdDirection.BELOW and critical > warning:
            raise ValueError(f"host metrics threshold {kind} critical must not exceed warning")
        normalized[kind] = ThresholdDefinition(
            direction=direction,
            warning=warning,
            critical=critical,
            sustained_samples=sustained_samples,
        )
    return normalized


def _numeric_status(value: float, threshold: ThresholdDefinition) -> Status:
    if threshold.direction == ThresholdDirection.ABOVE:
        if threshold.critical is not None and value >= threshold.critical:
            return Status.UNAVAILABLE
        if threshold.warning is not None and value >= threshold.warning:
            return Status.DEGRADED
    elif threshold.direction == ThresholdDirection.BELOW:
        if threshold.critical is not None and value <= threshold.critical:
            return Status.UNAVAILABLE
        if threshold.warning is not None and value <= threshold.warning:
            return Status.DEGRADED
    return Status.HEALTHY


def _numeric_measurement(
    *,
    measurement_id: str,
    label: str,
    kind: str,
    value: float,
    unit: str,
    threshold: ThresholdDefinition,
    observed_at: str,
) -> Measurement:
    return Measurement(
        id=measurement_id,
        label=label,
        kind=kind,
        status=_numeric_status(value, threshold),
        value=value,
        unit=unit,
        thresholds=threshold,
        observed_at=observed_at,
        freshness=Freshness.FRESH,
    )


def _unknown_measurement(
    measurement_id: str,
    label: str,
    kind: str,
    *,
    threshold: ThresholdDefinition | None = None,
    unit: str | None = None,
    observed_at: str,
) -> Measurement:
    return Measurement(
        id=measurement_id,
        label=label,
        kind=kind,
        status=Status.UNKNOWN,
        value=None,
        unit=unit,
        detail="Not reported by the host metrics source.",
        thresholds=threshold,
        observed_at=observed_at,
        freshness=Freshness.UNKNOWN,
    )


def _overall_status(measurements: list[Measurement]) -> Status:
    statuses = {item.status for item in measurements if item.value is not None}
    if Status.UNAVAILABLE in statuses:
        return Status.UNAVAILABLE
    if Status.DEGRADED in statuses:
        return Status.DEGRADED
    if Status.HEALTHY in statuses:
        return Status.HEALTHY
    return Status.UNKNOWN


def normalize_host_metrics(
    payload: Any,
    threshold_config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> HostMetricsStatus:
    """Validate one host metrics payload and normalize it into API v3 measurements.

    Payload schema version ``1`` accepts only ``observed_at``, ``boot_id``,
    ``disks``, ``temperatures``, ``smart``, ``backups``, ``cpu``, and ``memory``.
    Missing optional categories produce explicit unknown measurements.
    """
    root = _mapping(payload, "root", _PAYLOAD_KEYS, {"schema_version", "observed_at"})
    if root["schema_version"] != "1":
        raise _malformed("schema_version must be '1'")
    observed = _timestamp(root["observed_at"], "observed_at")
    observed_at = _timestamp_text(observed)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    thresholds = _thresholds(threshold_config)
    measurements: list[Measurement] = []

    raw_disks = _items(root.get("disks", []), "disks")
    for index, raw in enumerate(raw_disks):
        path = f"disks[{index}]"
        item = _mapping(raw, path, {"id", "label", "used_percent"}, {"id", "used_percent"})
        item_id = _identifier(item["id"], f"{path}.id")
        value = _number(item["used_percent"], f"{path}.used_percent", minimum=0, maximum=100)
        measurements.append(
            _numeric_measurement(
                measurement_id=f"disk:{item_id}:used_percent",
                label=_label(item.get("label"), item_id, f"{path}.label"),
                kind="disk_used_percent",
                value=value,
                unit="%",
                threshold=thresholds["disk_used_percent"],
                observed_at=observed_at,
            )
        )
    if not raw_disks:
        measurements.append(
            _unknown_measurement(
                "disk:unknown:used_percent",
                "Disk utilization",
                "disk_used_percent",
                threshold=thresholds["disk_used_percent"],
                unit="%",
                observed_at=observed_at,
            )
        )

    raw_temperatures = _items(root.get("temperatures", []), "temperatures")
    for index, raw in enumerate(raw_temperatures):
        path = f"temperatures[{index}]"
        item = _mapping(raw, path, {"id", "label", "celsius"}, {"id", "celsius"})
        item_id = _identifier(item["id"], f"{path}.id")
        value = _number(item["celsius"], f"{path}.celsius", minimum=-273.15, maximum=1000)
        measurements.append(
            _numeric_measurement(
                measurement_id=f"temperature:{item_id}",
                label=_label(item.get("label"), item_id, f"{path}.label"),
                kind="temperature_c",
                value=value,
                unit="°C",
                threshold=thresholds["temperature_c"],
                observed_at=observed_at,
            )
        )
    if not raw_temperatures:
        measurements.append(
            _unknown_measurement(
                "temperature:unknown",
                "Temperature",
                "temperature_c",
                threshold=thresholds["temperature_c"],
                unit="°C",
                observed_at=observed_at,
            )
        )

    raw_smart = _items(root.get("smart", []), "smart")
    for index, raw in enumerate(raw_smart):
        path = f"smart[{index}]"
        item = _mapping(raw, path, {"id", "label", "status"}, {"id", "status"})
        item_id = _identifier(item["id"], f"{path}.id")
        smart_status = item["status"]
        if not isinstance(smart_status, str) or smart_status not in {
            "passed",
            "failed",
            "unknown",
        }:
            raise _malformed(f"{path}.status must be 'passed', 'failed', or 'unknown'")
        normalized_status = {
            "passed": Status.HEALTHY,
            "failed": Status.UNAVAILABLE,
            "unknown": Status.UNKNOWN,
        }[smart_status]
        measurements.append(
            Measurement(
                id=f"smart:{item_id}",
                label=_label(item.get("label"), item_id, f"{path}.label"),
                kind="smart_health",
                status=normalized_status,
                value=smart_status,
                thresholds=ThresholdDefinition(direction=ThresholdDirection.CATEGORICAL),
                observed_at=observed_at,
                freshness=Freshness.FRESH,
            )
        )
    if not raw_smart:
        measurements.append(
            _unknown_measurement(
                "smart:unknown",
                "SMART health",
                "smart_health",
                threshold=ThresholdDefinition(direction=ThresholdDirection.CATEGORICAL),
                observed_at=observed_at,
            )
        )

    raw_backups = _items(root.get("backups", []), "backups")
    for index, raw in enumerate(raw_backups):
        path = f"backups[{index}]"
        item = _mapping(
            raw,
            path,
            {"id", "label", "last_success_at"},
            {"id", "last_success_at"},
        )
        item_id = _identifier(item["id"], f"{path}.id")
        last_success = _timestamp(item["last_success_at"], f"{path}.last_success_at")
        age_hours = (current - last_success).total_seconds() / 3600
        if age_hours < 0:
            raise _malformed(f"{path}.last_success_at must not be in the future")
        measurement = _numeric_measurement(
            measurement_id=f"backup:{item_id}:age",
            label=_label(item.get("label"), item_id, f"{path}.label"),
            kind="backup_age_hours",
            value=round(age_hours, 3),
            unit="h",
            threshold=thresholds["backup_age_hours"],
            observed_at=observed_at,
        )
        measurement.detail = f"Last successful backup: {_timestamp_text(last_success)}"
        measurements.append(measurement)
    if not raw_backups:
        measurements.append(
            _unknown_measurement(
                "backup:unknown:age",
                "Backup age",
                "backup_age_hours",
                threshold=thresholds["backup_age_hours"],
                unit="h",
                observed_at=observed_at,
            )
        )

    for field, label in (("cpu", "CPU utilization"), ("memory", "Memory utilization")):
        kind = f"{field}_used_percent"
        raw = root.get(field)
        if raw is None:
            measurements.append(
                _unknown_measurement(
                    f"{field}:used_percent",
                    label,
                    kind,
                    threshold=thresholds[kind],
                    unit="%",
                    observed_at=observed_at,
                )
            )
            continue
        item = _mapping(raw, field, {"used_percent"}, {"used_percent"})
        value = _number(item["used_percent"], f"{field}.used_percent", minimum=0, maximum=100)
        measurements.append(
            _numeric_measurement(
                measurement_id=f"{field}:used_percent",
                label=label,
                kind=kind,
                value=value,
                unit="%",
                threshold=thresholds[kind],
                observed_at=observed_at,
            )
        )

    boot_id = root.get("boot_id")
    if boot_id is not None:
        boot_id = _identifier(boot_id, "boot_id")
        measurements.append(
            Measurement(
                id="system:boot_id",
                label="Boot identity",
                kind="boot_id",
                status=Status.UNKNOWN,
                value=boot_id,
                detail="A persisted baseline is required before reboot status can be evaluated.",
                thresholds=ThresholdDefinition(direction=ThresholdDirection.CATEGORICAL),
                observed_at=observed_at,
                freshness=Freshness.FRESH,
            )
        )
    else:
        measurements.append(
            _unknown_measurement(
                "system:boot_id",
                "Boot identity",
                "boot_id",
                threshold=ThresholdDefinition(direction=ThresholdDirection.CATEGORICAL),
                observed_at=observed_at,
            )
        )

    return HostMetricsStatus(
        status=_overall_status(measurements),
        measurements=measurements,
        boot_id=boot_id,
        observed_at=observed_at,
        last_success_at=observed_at,
        freshness=Freshness.FRESH,
    )


class HostMetricsClient:
    """Read one strict host metrics payload over verified HTTPS."""

    def __init__(
        self,
        config: dict[str, Any],
        timeout: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.url = str(config["url"])
        if not self.url.startswith("https://"):
            raise ValueError("host metrics URL must use HTTPS")
        headers = {"Accept": "application/json"}
        token = config.get("api_key")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._headers = headers
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            verify=tls_verification(config),
            headers=headers,
            follow_redirects=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def collect(self, *, now: datetime | None = None) -> HostMetricsStatus:
        started = monotonic()
        try:
            response = self.client.get(self.url, headers=self._headers)
            response.raise_for_status()
            result = normalize_host_metrics(
                response.json(),
                self.config["thresholds"],
                now=now,
            )
            result.probe_duration_ms = max(1, round((monotonic() - started) * 1000))
            return result
        finally:
            self.close()
