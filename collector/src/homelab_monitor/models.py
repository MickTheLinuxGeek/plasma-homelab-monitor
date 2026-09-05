"""Normalized API models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

API_VERSION = "1"
COLLECTOR_VERSION = "0.2.0"


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Status(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class HostStatus:
    id: str
    name: str
    status: Status
    detail: str
    dashboard_url: str | None = None
    latency_ms: int | None = None
    observed_at: str = field(default_factory=utc_timestamp)
    last_success_at: str | None = None

    def __post_init__(self) -> None:
        if self.last_success_at is None and self.status != Status.UNAVAILABLE:
            self.last_success_at = self.observed_at


@dataclass(slots=True)
class ContainerStatus:
    id: str
    name: str
    image: str
    state: str
    status: Status
    detail: str


@dataclass(slots=True)
class DockerEnvironment:
    id: int
    name: str
    status: Status
    running: int
    stopped: int
    total: int
    containers: list[ContainerStatus] = field(default_factory=list)


@dataclass(slots=True)
class DockerStatus:
    status: Status = Status.UNKNOWN
    environments: list[DockerEnvironment] = field(default_factory=list)
    error: str | None = None
    observed_at: str = field(default_factory=utc_timestamp)
    last_success_at: str | None = None

    def __post_init__(self) -> None:
        if self.last_success_at is None and not self.error and self.status != Status.UNKNOWN:
            self.last_success_at = self.observed_at


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
    error: str | None = None
    observed_at: str = field(default_factory=utc_timestamp)
    last_success_at: str | None = None

    def __post_init__(self) -> None:
        if self.last_success_at is None and not self.error and self.status != Status.UNKNOWN:
            self.last_success_at = self.observed_at


@dataclass(slots=True)
class SourceError:
    source: str
    message: str
    observed_at: str = field(default_factory=utc_timestamp)


@dataclass(slots=True)
class Dashboard:
    hosts: list[HostStatus] = field(default_factory=list)
    docker: DockerStatus = field(default_factory=DockerStatus)
    jellyfin: JellyfinStatus = field(default_factory=JellyfinStatus)
    errors: list[SourceError] = field(default_factory=list)
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
