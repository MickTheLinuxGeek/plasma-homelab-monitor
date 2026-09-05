from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from homelab_monitor.models import Status
from homelab_monitor.providers.portainer import InspectCacheEntry, PortainerClient


def _config(**overrides: Any) -> dict[str, Any]:
    config = {
        "url": "https://portainer.example.test",
        "api_key": "test",
        "verify_tls": True,
        "endpoint_ids": [],
        "max_inspections_per_poll": 1,
        "inspect_baseline_interval_seconds": 300,
        "restart_warning_count": 3,
        "restart_critical_count": 10,
        "recent_exit_window_seconds": 3600,
        "endpoint_host_map": {"1": "nas"},
    }
    config.update(overrides)
    return config


def _inspect(
    *,
    state: str = "running",
    health: str = "healthy",
    failing_streak: int = 0,
    restart_count: int = 0,
    restarting: bool = False,
    oom_killed: bool = False,
    exit_code: int = 0,
    started_at: str | None = "2026-09-05T10:00:00Z",
    finished_at: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    labels = {"com.docker.compose.project": project} if project else {}
    return {
        "RestartCount": restart_count,
        "State": {
            "Status": state,
            "Restarting": restarting,
            "OOMKilled": oom_killed,
            "ExitCode": exit_code,
            "StartedAt": started_at,
            "FinishedAt": finished_at,
            "Health": {"Status": health, "FailingStreak": failing_streak},
        },
        "Config": {"Labels": labels},
    }


def test_selective_inspect_normalizes_container_failure_signals() -> None:
    now = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
    inspected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/endpoints":
            return httpx.Response(200, json=[{"Id": 1, "Name": "NAS", "Status": 1}])
        if request.url.path.endswith("/containers/json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": "healthy",
                        "Names": ["/web"],
                        "Image": "example/web:latest",
                        "State": "running",
                        "Status": "Up 2 hours (healthy)",
                        "Labels": {"com.docker.compose.project": "frontend"},
                    },
                    {
                        "Id": "unhealthy",
                        "Names": ["/worker"],
                        "Image": "example/worker:latest",
                        "State": "running",
                        "Status": "Up 3 minutes (unhealthy)",
                        "Labels": {"com.docker.compose.project": "old-project"},
                    },
                    {
                        "Id": "restarting",
                        "Names": ["/database"],
                        "Image": "postgres:17",
                        "State": "restarting",
                        "Status": "Restarting (1) 5 seconds ago",
                        "Labels": {"com.docker.stack.namespace": "storage"},
                    },
                ],
            )
        if "/containers/" in request.url.path:
            container_id = request.url.path.rsplit("/", 2)[-2]
            inspected.append(container_id)
            return httpx.Response(
                200,
                json=_inspect(
                    state="exited",
                    health="unhealthy",
                    failing_streak=4,
                    restart_count=12,
                    oom_killed=True,
                    exit_code=137,
                    finished_at="2026-09-05T17:50:00Z",
                    project="jobs",
                ),
            )
        return httpx.Response(404)

    result = PortainerClient(
        _config(),
        timeout=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: now,
    ).collect()
    environment = result.environments[0]
    containers = {item.id: item for item in environment.containers}
    failed = containers["unhealthy"]

    assert inspected == ["unhealthy"]
    assert result.status == Status.DEGRADED
    assert environment.host_id == "nas"
    assert containers["healthy"].health == "healthy"
    assert containers["healthy"].project == "frontend"
    assert containers["restarting"].status == Status.DEGRADED
    assert containers["restarting"].project == "storage"
    assert failed.state == "exited"
    assert failed.health == "unhealthy"
    assert failed.health_failing_streak == 4
    assert failed.restart_count == 12
    assert failed.oom_killed is True
    assert failed.exit_code == 137
    assert failed.started_at == "2026-09-05T10:00:00.000+00:00"
    assert failed.finished_at == "2026-09-05T17:50:00.000+00:00"
    assert failed.recent_exit is True
    assert failed.project == "jobs"
    assert failed.status == Status.UNAVAILABLE


def test_maximum_inspections_is_enforced_across_all_endpoints() -> None:
    inspected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/endpoints":
            return httpx.Response(
                200,
                json=[
                    {"Id": 1, "Name": "One", "Status": 1},
                    {"Id": 2, "Name": "Two", "Status": 1},
                ],
            )
        if request.url.path.endswith("/containers/json"):
            endpoint_id = request.url.path.split("/")[3]
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": f"bad-{endpoint_id}",
                        "Names": [f"/bad-{endpoint_id}"],
                        "Image": "example/bad",
                        "State": "running",
                        "Status": "Up 1 minute (unhealthy)",
                    }
                ],
            )
        if "/containers/" in request.url.path:
            inspected.append(request.url.path)
            return httpx.Response(200, json=_inspect(health="unhealthy", failing_streak=1))
        return httpx.Response(404)

    result = PortainerClient(
        _config(endpoint_host_map={"1": "one", "2": "two"}),
        timeout=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: datetime(2026, 9, 5, 18, 0, tzinfo=UTC),
    ).collect()

    assert len(inspected) == 1
    assert result.environments[0].host_id == "one"
    assert result.environments[1].host_id == "two"
    assert result.environments[1].containers[0].health == "unhealthy"


def test_inspect_cache_rotates_periodic_baselines_without_reinspection() -> None:
    start = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)
    current = start
    cache: dict[tuple[int, str], InspectCacheEntry] = {}
    inspected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/endpoints":
            return httpx.Response(200, json=[{"Id": 1, "Name": "NAS", "Status": 1}])
        if request.url.path.endswith("/containers/json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": "first",
                        "Names": ["/first"],
                        "Image": "example/first",
                        "State": "running",
                        "Status": "Up 1 hour (healthy)",
                    },
                    {
                        "Id": "second",
                        "Names": ["/second"],
                        "Image": "example/second",
                        "State": "running",
                        "Status": "Up 1 hour (healthy)",
                    },
                ],
            )
        if "/containers/" in request.url.path:
            container_id = request.url.path.rsplit("/", 2)[-2]
            inspected.append(container_id)
            return httpx.Response(200, json=_inspect(restart_count=len(inspected)))
        return httpx.Response(404)

    for offset in (0, 60, 301):
        current = start + timedelta(seconds=offset)
        PortainerClient(
            _config(),
            timeout=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            inspect_cache=cache,
            clock=lambda current=current: current,
        ).collect()

    assert inspected == ["first", "second", "first"]
    assert cache[(1, "first")].detail["restart_count"] == 3
    assert cache[(1, "second")].detail["restart_count"] == 2
