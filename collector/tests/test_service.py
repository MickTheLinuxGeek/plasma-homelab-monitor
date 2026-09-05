from __future__ import annotations

from collections.abc import Callable
from threading import Event, Lock
from time import monotonic, sleep

import httpx
from homelab_monitor.models import Freshness, HostStatus, Status
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
