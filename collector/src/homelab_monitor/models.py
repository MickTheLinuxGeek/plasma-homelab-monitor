"""Normalized API models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

LEGACY_API_VERSION = "1"
COMPAT_API_VERSION = "2"
API_VERSION = "3"
COLLECTOR_VERSION = "0.4.0"


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Status(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class ErrorCategory(StrEnum):
    TIMEOUT = "timeout"
    TLS = "tls"
    AUTHENTICATION = "authentication"
    DNS = "dns"
    CONNECTION = "connection"
    MALFORMED_RESPONSE = "malformed_response"
    UNEXPECTED = "unexpected"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ThresholdDirection(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    CATEGORICAL = "categorical"


@dataclass(slots=True)
class ProviderError:
    category: ErrorCategory
    message: str


@dataclass(slots=True)
class ThresholdDefinition:
    direction: ThresholdDirection
    warning: float | None = None
    critical: float | None = None
    sustained_samples: int = 1


@dataclass(slots=True)
class Measurement:
    id: str
    label: str
    kind: str
    status: Status
    value: float | int | str | bool | None
    unit: str | None = None
    detail: str = ""
    thresholds: ThresholdDefinition | None = None
    observed_at: str | None = None
    freshness: Freshness = Freshness.UNKNOWN


@dataclass(slots=True)
class HostMetricsStatus:
    status: Status = Status.UNKNOWN
    measurements: list[Measurement] = field(default_factory=list)
    boot_id: str | None = None
    error: ProviderError | None = None
    observed_at: str | None = None
    last_success_at: str | None = None
    consecutive_failure_count: int = 0
    probe_duration_ms: int | None = None
    freshness: Freshness = Freshness.UNKNOWN


@dataclass(slots=True)
class HostStatus:
    id: str
    name: str
    status: Status
    detail: str
    dashboard_url: str | None = None
    latency_ms: int | None = None
    observed_at: str | None = None
    last_success_at: str | None = None
    consecutive_failure_count: int = 0
    probe_duration_ms: int | None = None
    freshness: Freshness = Freshness.UNKNOWN
    error: ProviderError | None = None
    certificate_expires_at: str | None = None
    certificate_days_remaining: int | None = None
    metrics: HostMetricsStatus | None = None


@dataclass(slots=True)
class ContainerStatus:
    id: str
    name: str
    image: str
    state: str
    status: Status
    detail: str
    health: str = "none"
    health_failing_streak: int = 0
    restart_count: int | None = None
    restarting: bool = False
    oom_killed: bool = False
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    recent_exit: bool = False
    project: str | None = None


@dataclass(slots=True)
class DockerEnvironment:
    id: int
    name: str
    status: Status
    running: int
    stopped: int
    total: int
    containers: list[ContainerStatus] = field(default_factory=list)
    host_id: str | None = None


@dataclass(slots=True)
class DockerStatus:
    status: Status = Status.UNKNOWN
    environments: list[DockerEnvironment] = field(default_factory=list)
    error: ProviderError | None = None
    observed_at: str | None = None
    last_success_at: str | None = None
    consecutive_failure_count: int = 0
    probe_duration_ms: int | None = None
    freshness: Freshness = Freshness.UNKNOWN


@dataclass(slots=True)
class JellyfinSession:
    user_name: str
    client: str
    device_name: str
    item_name: str


@dataclass(slots=True)
class JellyfinStatus:
    status: Status = Status.UNKNOWN
    server_name: str = ""
    version: str = ""
    active_sessions: list[JellyfinSession] = field(default_factory=list)
    dashboard_url: str | None = None
    error: ProviderError | None = None
    observed_at: str | None = None
    last_success_at: str | None = None
    consecutive_failure_count: int = 0
    probe_duration_ms: int | None = None
    freshness: Freshness = Freshness.UNKNOWN


@dataclass(slots=True)
class SourceError:
    source: str
    category: ErrorCategory
    message: str
    observed_at: str = field(default_factory=utc_timestamp)


@dataclass(slots=True)
class TimelineEvent:
    id: int
    resource_id: str
    resource_name: str
    event_type: str
    severity: Severity
    message: str
    occurred_at: str
    previous_status: Status | None = None
    current_status: Status | None = None
    incident_id: int | None = None
    parent_event_id: int | None = None
    recovered_at: str | None = None


@dataclass(slots=True)
class TrendPoint:
    observed_at: str
    status: Status
    value: float | int | None = None


@dataclass(slots=True)
class TrendSeries:
    resource_id: str
    label: str
    metric: str
    unit: str | None = None
    points: list[TrendPoint] = field(default_factory=list)


@dataclass(slots=True)
class FeatureStatus:
    history_enabled: bool = False
    history_available: bool = False
    history_retention_days: int = 0
    notifications_enabled: bool = False


@dataclass(slots=True)
class Dashboard:
    hosts: list[HostStatus] = field(default_factory=list)
    docker: DockerStatus = field(default_factory=DockerStatus)
    jellyfin: JellyfinStatus = field(default_factory=JellyfinStatus)
    errors: list[SourceError] = field(default_factory=list)
    recent_events: list[TimelineEvent] = field(default_factory=list)
    trends: list[TrendSeries] = field(default_factory=list)
    features: FeatureStatus = field(default_factory=FeatureStatus)
    schema_version: str = API_VERSION
    api_version: str = API_VERSION
    collector_version: str = COLLECTOR_VERSION
    generated_at: str = field(default_factory=utc_timestamp)

    def overall_status(self) -> Status:
        statuses = [host.status for host in self.hosts]
        if self.docker.status != Status.UNKNOWN:
            statuses.append(self.docker.status)
        if self.jellyfin.status != Status.UNKNOWN:
            statuses.append(self.jellyfin.status)
        if not statuses:
            return Status.UNKNOWN
        if all(status == Status.HEALTHY for status in statuses):
            return Status.HEALTHY
        if all(status == Status.UNAVAILABLE for status in statuses):
            return Status.UNAVAILABLE
        return Status.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["overall_status"] = self.overall_status().value
        counts = {status.value: 0 for status in Status}
        for host in self.hosts:
            counts[host.status.value] += 1
        for provider_status in (self.docker.status, self.jellyfin.status):
            if provider_status != Status.UNKNOWN:
                counts[provider_status.value] += 1
        payload["summary"] = counts
        successful_observations = [
            item.last_success_at
            for item in [*self.hosts, self.docker, self.jellyfin]
            if item.last_success_at
        ]
        payload["last_successful_observation_at"] = (
            max(successful_observations) if successful_observations else None
        )
        return payload

    def to_v2_dict(self) -> dict[str, Any]:
        """Return the strict v0.3 response shape for API v2 clients."""
        payload = self.to_dict()
        payload["schema_version"] = COMPAT_API_VERSION
        payload["api_version"] = COMPAT_API_VERSION
        for field_name in ("recent_events", "trends", "features"):
            payload.pop(field_name, None)
        for host in payload["hosts"]:
            for field_name in (
                "certificate_expires_at",
                "certificate_days_remaining",
                "metrics",
            ):
                host.pop(field_name, None)
        for environment in payload["docker"]["environments"]:
            environment.pop("host_id", None)
            for container in environment["containers"]:
                for field_name in (
                    "health",
                    "health_failing_streak",
                    "restart_count",
                    "restarting",
                    "oom_killed",
                    "exit_code",
                    "started_at",
                    "finished_at",
                    "recent_exit",
                    "project",
                ):
                    container.pop(field_name, None)
        return payload

    def to_v1_dict(self) -> dict[str, Any]:
        """Return the pre-v0.3 response shape for existing v1 clients."""
        payload = self.to_v2_dict()
        payload["schema_version"] = LEGACY_API_VERSION
        payload["api_version"] = LEGACY_API_VERSION
        provider_state_fields = {
            "consecutive_failure_count",
            "probe_duration_ms",
            "freshness",
        }
        for host in payload["hosts"]:
            host.pop("error", None)
            for field_name in provider_state_fields:
                host.pop(field_name, None)
        for provider_name in ("docker", "jellyfin"):
            provider = payload[provider_name]
            error = provider.get("error")
            provider["error"] = error["message"] if error else None
            for field_name in provider_state_fields:
                provider.pop(field_name, None)
        payload["errors"] = [
            {"source": item["source"], "message": item["message"]} for item in payload["errors"]
        ]
        return payload
