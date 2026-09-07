from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from time import monotonic, sleep

import httpx
from homelab_monitor.contracts import NotificationMessage
from homelab_monitor.history import HistoryStore
from homelab_monitor.models import (
    Freshness,
    HostMetricsStatus,
    HostStatus,
    Measurement,
    Status,
    ThresholdDefinition,
    ThresholdDirection,
)
from homelab_monitor.service import DashboardService


def _config(host_ids: list[str], *, concurrency: int = 2, interval: float = 0.05) -> dict:
    return {
        "demo": False,
        "request_timeout_seconds": 0.1,
        "poll_interval_seconds": interval,
        "max_concurrent_probes": concurrency,
        "retry_base_seconds": 0.01,
        "retry_max_seconds": 0.02,
        "freshness_grace_seconds": 0.01,
        "hosts": [
            {
                "id": host_id,
                "name": host_id,
                "poll_interval_seconds": interval,
                "timeout_seconds": 0.1,
                "probe": {"type": "tcp", "host": "127.0.0.1", "port": 1},
            }
            for host_id in host_ids
        ],
        "portainer": {"enabled": False},
        "jellyfin": {"enabled": False},
    }


def _healthy(host_id: str) -> HostStatus:
    return HostStatus(host_id, host_id, Status.HEALTHY, "Online")


def _wait_for(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_snapshot_does_not_wait_for_in_progress_provider_io() -> None:
    entered = Event()
    release = Event()

    def slow_probe() -> HostStatus:
        entered.set()
        release.wait(1)
        return _healthy("slow")

    service = DashboardService(_config(["slow"]), {"host:slow": slow_probe})
    service.start()
    assert entered.wait(0.5)

    started = monotonic()
    snapshot = service.snapshot()
    elapsed = monotonic() - started

    release.set()
    service.stop()
    assert elapsed < 0.05
    assert snapshot.hosts[0].status == Status.UNKNOWN


def test_slow_provider_does_not_block_healthy_provider() -> None:
    slow_entered = Event()
    slow_release = Event()

    def slow_probe() -> HostStatus:
        slow_entered.set()
        slow_release.wait(1)
        return _healthy("slow")

    service = DashboardService(
        _config(["slow", "fast"], concurrency=2),
        {"host:slow": slow_probe, "host:fast": lambda: _healthy("fast")},
    )
    service.start()
    assert slow_entered.wait(0.5)
    _wait_for(
        lambda: (
            next(item for item in service.snapshot().hosts if item.id == "fast").observed_at
            is not None
        )
    )
    snapshot = service.snapshot()

    slow_release.set()
    service.stop()
    fast = next(item for item in snapshot.hosts if item.id == "fast")
    slow = next(item for item in snapshot.hosts if item.id == "slow")
    assert fast.status == Status.HEALTHY
    assert fast.freshness == Freshness.FRESH
    assert slow.status == Status.UNKNOWN


def test_concurrency_limit_is_enforced() -> None:
    lock = Lock()
    active = 0
    peak = 0

    def probe(host_id: str) -> Callable[[], HostStatus]:
        def collect() -> HostStatus:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            sleep(0.03)
            with lock:
                active -= 1
            return _healthy(host_id)

        return collect

    service = DashboardService(
        _config(["one", "two"], concurrency=1, interval=1),
        {"host:one": probe("one"), "host:two": probe("two")},
    )
    service.start()
    assert service.wait_until_ready(1)
    service.stop()

    assert peak == 1


def test_failure_preserves_last_known_good_with_stale_metadata() -> None:
    calls = 0

    def changing_probe() -> HostStatus:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _healthy("host")
        raise httpx.ReadTimeout("secret upstream detail")

    service = DashboardService(_config(["host"], interval=0.02), {"host:host": changing_probe})
    service.start()
    _wait_for(lambda: service.snapshot().hosts[0].last_success_at is not None)
    first_success = service.snapshot().hosts[0].last_success_at
    _wait_for(lambda: service.snapshot().hosts[0].error is not None)
    snapshot = service.snapshot()
    failed = snapshot.hosts[0]
    service.stop()

    assert failed.status == Status.UNAVAILABLE
    assert failed.detail == "Online"
    assert failed.last_success_at == first_success
    assert failed.freshness == Freshness.STALE
    assert failed.consecutive_failure_count >= 1
    assert failed.error.category == "timeout"
    assert "secret upstream detail" not in failed.error.message
    assert snapshot.errors[0].source == "host:host"
    assert snapshot.errors[0].category == "timeout"


def test_retry_delay_is_exponential_and_bounded() -> None:
    service = DashboardService(_config([]))

    assert service.retry_delay(60, 1) == 0.01
    assert service.retry_delay(60, 2) == 0.02
    assert service.retry_delay(60, 20) == 0.02


def _enable_history(config: dict, path, *, notifications: bool = False) -> None:
    config["history"] = {
        "enabled": True,
        "path": str(path),
        "retention_days": 30,
        "max_observations_per_resource": 100,
        "max_total_observations": 1000,
        "recent_event_limit": 20,
        "trend_point_limit": 30,
        "queue_size": 64,
    }
    config["notifications"] = {
        "enabled": notifications,
        "minimum_severity": "warning",
        "degraded_grace_seconds": 0,
        "unavailable_grace_seconds": 0,
        "cooldown_seconds": 0,
        "recovery_messages": True,
        "queue_size": 16,
        "retry_limit": 2,
        "quiet_hours": {
            "enabled": False,
            "start": "22:00",
            "end": "07:00",
            "timezone": "UTC",
        },
    }


def test_metrics_failure_is_attached_without_marking_host_unavailable() -> None:
    config = _config(["nas"], interval=0.02)
    config["hosts"][0]["metrics"] = {
        "enabled": True,
        "poll_interval_seconds": 0.02,
        "timeout_seconds": 0.1,
    }
    calls = 0

    def metrics() -> HostMetricsStatus:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise httpx.ReadTimeout("metrics unavailable")
        return HostMetricsStatus(
            status=Status.DEGRADED,
            boot_id="boot-1",
            measurements=[
                Measurement(
                    id="cpu:used_percent",
                    label="CPU",
                    kind="cpu_used_percent",
                    status=Status.DEGRADED,
                    value=90,
                    unit="%",
                    thresholds=ThresholdDefinition(
                        direction=ThresholdDirection.ABOVE,
                        warning=85,
                        critical=95,
                        sustained_samples=3,
                    ),
                    freshness=Freshness.FRESH,
                )
            ],
        )

    service = DashboardService(
        config,
        {
            "host:nas": lambda: _healthy("nas"),
            "metrics:nas": metrics,
        },
    )
    service.start()
    _wait_for(lambda: service.snapshot().hosts[0].metrics is not None)
    _wait_for(lambda: service.snapshot().hosts[0].metrics.error is not None)
    snapshot = service.snapshot()
    service.stop()

    assert snapshot.hosts[0].status == Status.HEALTHY
    assert snapshot.hosts[0].metrics.status == Status.UNAVAILABLE
    assert snapshot.hosts[0].metrics.freshness == Freshness.STALE
    assert snapshot.hosts[0].metrics.measurements[0].freshness == Freshness.STALE
    assert any(error.source == "metrics:nas" for error in snapshot.errors)


def test_service_persists_history_and_serves_cached_events(tmp_path) -> None:
    config = _config(["nas"], interval=0.02)
    path = tmp_path / "history.sqlite3"
    _enable_history(config, path)
    calls = 0

    def changing_probe() -> HostStatus:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _healthy("nas")
        raise httpx.ConnectError("offline")

    service = DashboardService(config, {"host:nas": changing_probe})
    service.start()
    _wait_for(lambda: bool(service.snapshot().recent_events))
    snapshot = service.snapshot()
    service.stop()

    assert snapshot.features.history_enabled is True
    assert snapshot.features.history_available is True
    assert snapshot.recent_events[0].resource_id == "host:nas"
    assert snapshot.recent_events[0].current_status == Status.UNAVAILABLE
    assert snapshot.trends[0].metric == "latency_ms"

    reopened = HistoryStore(path)
    assert reopened.schema_version() == 2
    assert reopened.read_model().recent_events
    reopened.close()


def test_service_dispatches_each_incident_notification_once(tmp_path) -> None:
    class CaptureSink:
        def __init__(self) -> None:
            self.messages: list[NotificationMessage] = []

        def send(self, message: NotificationMessage) -> None:
            self.messages.append(message)

    config = _config(["nas"], interval=0.02)
    path = tmp_path / "history.sqlite3"
    _enable_history(config, path, notifications=True)
    sink = CaptureSink()

    def unavailable() -> HostStatus:
        raise httpx.ConnectError("offline")

    service = DashboardService(
        config,
        {"host:nas": unavailable},
        notification_sink=sink,
    )
    service.start()
    _wait_for(lambda: len(sink.messages) == 1)
    sleep(0.08)
    service.stop()

    assert len(sink.messages) == 1
    assert sink.messages[0].severity == "critical"
