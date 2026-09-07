"""Read-only Portainer API adapter with bounded container detail inspection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from homelab_monitor.errors import MalformedResponseError
from homelab_monitor.models import (
    ContainerStatus,
    DockerEnvironment,
    DockerStatus,
    Status,
)
from homelab_monitor.tls import tls_verification

_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
_STACK_NAMESPACE_LABEL = "com.docker.stack.namespace"
InspectCacheKey = tuple[int, str]


@dataclass(slots=True)
class InspectCacheEntry:
    """One sanitized container inspect detail and its wall-clock baseline."""

    detail: dict[str, Any]
    inspected_at: datetime


def _malformed(message: str) -> MalformedResponseError:
    return MalformedResponseError(f"Portainer {message}")


def _timestamp(value: Any, field: str) -> str | None:
    if value in (None, "", "0001-01-01T00:00:00Z", "0001-01-01T00:00:00.000000000Z"):
        return None
    if not isinstance(value, str):
        raise _malformed(f"container inspect {field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _malformed(f"container inspect {field} must be a timestamp") from exc
    if parsed.tzinfo is None:
        raise _malformed(f"container inspect {field} must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds")


def _labels(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise _malformed(f"{field} must be an object of string labels")
    return value


def _project(labels: dict[str, str]) -> str | None:
    return labels.get(_COMPOSE_PROJECT_LABEL) or labels.get(_STACK_NAMESPACE_LABEL) or None


def _list_health(state: str, detail: str) -> str:
    lowered = detail.lower()
    if "(unhealthy)" in lowered:
        return "unhealthy"
    if "(healthy)" in lowered:
        return "healthy"
    if "health: starting" in lowered or "(starting)" in lowered:
        return "starting"
    return "none" if state in {"running", "created", "exited", "dead"} else "unknown"


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool):
        raise _malformed(f"container inspect {field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _malformed(f"container inspect {field} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise _malformed(f"container inspect {field} is below the supported range")
    return result


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise _malformed(f"container inspect {field} must be true or false")
    return value


def _normalize_inspect(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _malformed("container inspect response must be an object")
    state = payload.get("State")
    if not isinstance(state, dict):
        raise _malformed("container inspect State must be an object")
    raw_health = state.get("Health")
    health = "none"
    failing_streak = 0
    if raw_health is not None:
        if not isinstance(raw_health, dict):
            raise _malformed("container inspect State.Health must be an object")
        health = str(raw_health.get("Status") or "unknown").lower()
        if health not in {"starting", "healthy", "unhealthy"}:
            health = "unknown"
        failing_streak = _integer(
            raw_health.get("FailingStreak", 0),
            "State.Health.FailingStreak",
            minimum=0,
        )
    raw_config = payload.get("Config")
    if raw_config is not None and not isinstance(raw_config, dict):
        raise _malformed("container inspect Config must be an object")
    labels = _labels((raw_config or {}).get("Labels"), "container inspect Config.Labels")
    return {
        "state": str(state.get("Status") or "unknown").lower(),
        "health": health,
        "health_failing_streak": failing_streak,
        "restart_count": _integer(payload.get("RestartCount", 0), "RestartCount", minimum=0),
        "restarting": _boolean(state.get("Restarting", False), "State.Restarting"),
        "oom_killed": _boolean(state.get("OOMKilled", False), "State.OOMKilled"),
        "exit_code": _integer(state.get("ExitCode", 0), "State.ExitCode"),
        "started_at": _timestamp(state.get("StartedAt"), "State.StartedAt"),
        "finished_at": _timestamp(state.get("FinishedAt"), "State.FinishedAt"),
        "project": _project(labels),
    }


def _is_recent(timestamp: str | None, now: datetime, window_seconds: float) -> bool:
    if timestamp is None:
        return False
    finished = datetime.fromisoformat(timestamp)
    age = (now - finished).total_seconds()
    return 0 <= age <= window_seconds


def _container_status(
    state: str,
    health: str,
    *,
    restarting: bool,
    oom_killed: bool,
    restart_count: int | None,
    restart_warning_count: int,
    restart_critical_count: int,
) -> Status:
    if oom_killed or state in {"dead", "exited"}:
        return Status.UNAVAILABLE
    if restart_count is not None and restart_count >= restart_critical_count:
        return Status.UNAVAILABLE
    if (
        restarting
        or state == "restarting"
        or health in {"starting", "unhealthy"}
        or (restart_count is not None and restart_count >= restart_warning_count)
    ):
        return Status.DEGRADED
    if state == "running" and health in {"none", "healthy"}:
        return Status.HEALTHY
    if state == "unknown":
        return Status.UNKNOWN
    return Status.DEGRADED


class PortainerClient:
    def __init__(
        self,
        config: dict[str, Any],
        timeout: float,
        client: httpx.Client | None = None,
        *,
        inspect_cache: dict[InspectCacheKey, InspectCacheEntry] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.base_url = str(config["url"]).rstrip("/")
        self.endpoint_ids = {int(value) for value in config.get("endpoint_ids", [])}
        self.max_inspections = int(config.get("max_inspections_per_poll", 20))
        self.baseline_interval = float(config.get("inspect_baseline_interval_seconds", 300))
        self.restart_warning_count = int(config.get("restart_warning_count", 3))
        self.restart_critical_count = int(config.get("restart_critical_count", 10))
        self.recent_exit_window = float(config.get("recent_exit_window_seconds", 3600))
        self.endpoint_host_map = {
            str(key): str(value) for key, value in config.get("endpoint_host_map", {}).items()
        }
        self.inspect_cache = inspect_cache if inspect_cache is not None else {}
        self._inspections_remaining = self.max_inspections
        self._clock = clock or (lambda: datetime.now(UTC))
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            verify=tls_verification(config),
            headers={"X-API-Key": str(config["api_key"])},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, path: str, **params: Any) -> Any:
        response = self.client.get(f"{self.base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def _listed_container(self, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise _malformed("container entry must be an object")
        container_id = item.get("Id")
        if not isinstance(container_id, str) or not container_id:
            raise _malformed("container Id must be a non-empty string")
        names = item.get("Names", [])
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise _malformed("container Names must be an array of strings")
        state = str(item.get("State") or "unknown").lower()
        detail = str(item.get("Status") or state.title())
        labels = _labels(item.get("Labels"), "container Labels")
        name = names[0].lstrip("/") if names else container_id[:12]
        return {
            "id": container_id,
            "name": name,
            "image": str(item.get("Image") or ""),
            "state": state,
            "detail": detail,
            "health": _list_health(state, detail),
            "project": _project(labels),
        }

    def _inspect(self, endpoint_id: int, container_id: str) -> dict[str, Any]:
        payload = self._get(f"/api/endpoints/{endpoint_id}/docker/containers/{container_id}/json")
        return _normalize_inspect(payload)

    def _needs_urgent_inspect(self, container: dict[str, Any]) -> bool:
        return (
            container["state"] != "running"
            or container["health"] in {"starting", "unhealthy", "unknown"}
            or "restarting" in container["detail"].lower()
        )

    def _select_inspections(
        self,
        endpoint_id: int,
        containers: list[dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        urgent = [item for item in containers if self._needs_urgent_inspect(item)]
        urgent_ids = {item["id"] for item in urgent}
        baseline = []
        for item in containers:
            if item["id"] in urgent_ids:
                continue
            cached = self.inspect_cache.get((endpoint_id, item["id"]))
            if (
                cached is None
                or (now - cached.inspected_at).total_seconds() >= self.baseline_interval
            ):
                baseline.append(item)
        return (urgent + baseline)[: self._inspections_remaining]

    def _container(
        self,
        endpoint_id: int,
        item: dict[str, Any],
        now: datetime,
    ) -> ContainerStatus:
        cached = self.inspect_cache.get((endpoint_id, item["id"]))
        detail = cached.detail if cached else {}
        state = str(detail.get("state") or item["state"])
        health = str(detail.get("health") or item["health"])
        restart_count = detail.get("restart_count")
        restarting = bool(detail.get("restarting", state == "restarting"))
        oom_killed = bool(detail.get("oom_killed", False))
        exit_code = detail.get("exit_code")
        started_at = detail.get("started_at")
        finished_at = detail.get("finished_at")
        project = detail.get("project") or item["project"]
        status = _container_status(
            state,
            health,
            restarting=restarting,
            oom_killed=oom_killed,
            restart_count=restart_count,
            restart_warning_count=self.restart_warning_count,
            restart_critical_count=self.restart_critical_count,
        )
        return ContainerStatus(
            id=item["id"],
            name=item["name"],
            image=item["image"],
            state=state,
            status=status,
            detail=item["detail"],
            health=health,
            health_failing_streak=int(detail.get("health_failing_streak", 0)),
            restart_count=restart_count,
            restarting=restarting,
            oom_killed=oom_killed,
            exit_code=exit_code,
            started_at=started_at,
            finished_at=finished_at,
            recent_exit=_is_recent(finished_at, now, self.recent_exit_window),
            project=project,
        )

    def _environment(
        self,
        endpoint_id: int,
        name: str,
        raw_containers: Any,
        now: datetime,
    ) -> DockerEnvironment:
        if not isinstance(raw_containers, list):
            raise _malformed("containers response must be a list")
        listed = [self._listed_container(item) for item in raw_containers]
        for item in self._select_inspections(endpoint_id, listed, now):
            key = (endpoint_id, item["id"])
            self.inspect_cache[key] = InspectCacheEntry(
                detail=self._inspect(endpoint_id, item["id"]),
                inspected_at=now,
            )
            self._inspections_remaining -= 1
        current_keys = {(endpoint_id, item["id"]) for item in listed}
        stale_keys = {
            key for key in self.inspect_cache if key[0] == endpoint_id and key not in current_keys
        }
        for key in stale_keys:
            del self.inspect_cache[key]

        containers = [self._container(endpoint_id, item, now) for item in listed]
        running = sum(item.state == "running" for item in containers)
        total = len(containers)
        stopped = total - running
        statuses = {item.status for item in containers}
        if not statuses or statuses == {Status.HEALTHY}:
            status = Status.HEALTHY
        elif statuses == {Status.UNAVAILABLE}:
            status = Status.UNAVAILABLE
        else:
            status = Status.DEGRADED
        return DockerEnvironment(
            id=endpoint_id,
            name=name,
            status=status,
            running=running,
            stopped=stopped,
            total=total,
            containers=containers,
            host_id=self.endpoint_host_map.get(str(endpoint_id)),
        )

    def collect(self) -> DockerStatus:
        try:
            endpoints = self._get("/api/endpoints")
            if not isinstance(endpoints, list):
                raise _malformed("endpoints response must be a list")
            now = self._clock().astimezone(UTC)
            self._inspections_remaining = self.max_inspections
            environments: list[DockerEnvironment] = []
            for endpoint in endpoints:
                if not isinstance(endpoint, dict):
                    raise _malformed("endpoint entry must be an object")
                try:
                    endpoint_id = int(endpoint["Id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise _malformed("endpoint Id must be an integer") from exc
                if self.endpoint_ids and endpoint_id not in self.endpoint_ids:
                    continue

                name = str(endpoint.get("Name") or f"Environment {endpoint_id}")
                if int(endpoint.get("Status", 0)) != 1:
                    environments.append(
                        DockerEnvironment(
                            id=endpoint_id,
                            name=name,
                            status=Status.UNAVAILABLE,
                            running=0,
                            stopped=0,
                            total=0,
                            host_id=self.endpoint_host_map.get(str(endpoint_id)),
                        )
                    )
                    continue

                raw_containers = self._get(
                    f"/api/endpoints/{endpoint_id}/docker/containers/json",
                    all="true",
                )
                environments.append(self._environment(endpoint_id, name, raw_containers, now))

            statuses = [item.status for item in environments]
            if not statuses or all(status == Status.HEALTHY for status in statuses):
                overall = Status.HEALTHY
            elif all(status == Status.UNAVAILABLE for status in statuses):
                overall = Status.UNAVAILABLE
            else:
                overall = Status.DEGRADED
            return DockerStatus(status=overall, environments=environments)
        finally:
            self.close()
