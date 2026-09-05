"""Background collection and cached dashboard snapshots."""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Event, Lock, Semaphore, Thread
from time import monotonic
from typing import Any

from homelab_monitor.demo import build_demo_dashboard
from homelab_monitor.errors import classify_provider_error
from homelab_monitor.models import (
    Dashboard,
    DockerStatus,
    Freshness,
    HostStatus,
    JellyfinStatus,
    ProviderError,
    SourceError,
    Status,
    utc_timestamp,
)
from homelab_monitor.providers import JellyfinClient, PortainerClient, probe_host

logger = logging.getLogger(__name__)
ProviderResult = HostStatus | DockerStatus | JellyfinStatus


@dataclass(slots=True)
class _ScheduledSource:
    key: str
    kind: str
    interval: float
    collect: Callable[[], ProviderResult]
    empty: Callable[[], ProviderResult]
    current: ProviderResult
    last_good: ProviderResult | None = None
    failures: int = 0
    thread: Thread | None = None


class DashboardService:
    """Poll providers independently and serve immutable cached snapshots."""

    def __init__(
        self,
        config: dict[str, Any],
        collector_overrides: dict[str, Callable[[], ProviderResult]] | None = None,
    ) -> None:
        self.config = config
        self.collector_overrides = collector_overrides or {}
        self._lock = Lock()
        self._stop_event = Event()
        self._ready_event = Event()
        self._semaphore = Semaphore(int(config.get("max_concurrent_probes", 4)))
        self._retry_base = float(config.get("retry_base_seconds", 2))
        self._retry_max = float(config.get("retry_max_seconds", 30))
        self._freshness_grace = float(config.get("freshness_grace_seconds", 5))
        self._started = False
        self._demo = bool(config.get("demo"))
        self._sources = self._build_sources()

    def _build_sources(self) -> list[_ScheduledSource]:
        sources: list[_ScheduledSource] = []
        default_timeout = float(self.config.get("request_timeout_seconds", 3))
        default_interval = float(self.config.get("poll_interval_seconds", 30))

        for index, host in enumerate(self.config.get("hosts", [])):
            host_id = str(host.get("id") or host.get("name") or index)
            key = f"host:{host_id}"
            timeout = float(host.get("timeout_seconds", default_timeout))

            def empty_host(host: dict[str, Any] = host, host_id: str = host_id) -> HostStatus:
                return HostStatus(
                    id=host_id,
                    name=str(host.get("name") or host_id),
                    status=Status.UNKNOWN,
                    detail="Waiting for the first observation.",
                    dashboard_url=host.get("dashboard_url"),
                )

            def collect_host(
                host: dict[str, Any] = host,
                timeout: float = timeout,
            ) -> HostStatus:
                return probe_host(host, timeout)

            empty = empty_host
            collect = self.collector_overrides.get(key, collect_host)
            sources.append(
                _ScheduledSource(
                    key=key,
                    kind="host",
                    interval=float(host.get("poll_interval_seconds", default_interval)),
                    collect=collect,
                    empty=empty,
                    current=empty(),
                )
            )

        portainer = self.config.get("portainer", {})
        if portainer.get("enabled"):
            key = "portainer"
            timeout = float(portainer.get("timeout_seconds", default_timeout))

            def empty_portainer() -> DockerStatus:
                return DockerStatus(status=Status.UNKNOWN)

            def collect_portainer() -> DockerStatus:
                return PortainerClient(portainer, timeout).collect()

            empty = empty_portainer
            collect = self.collector_overrides.get(key, collect_portainer)
            sources.append(
                _ScheduledSource(
                    key=key,
                    kind="docker",
                    interval=float(portainer.get("poll_interval_seconds", default_interval)),
                    collect=collect,
                    empty=empty,
                    current=empty(),
                )
            )

        jellyfin = self.config.get("jellyfin", {})
        if jellyfin.get("enabled"):
            key = "jellyfin"
            timeout = float(jellyfin.get("timeout_seconds", default_timeout))

            def empty_jellyfin() -> JellyfinStatus:
                return JellyfinStatus(
                    status=Status.UNKNOWN,
                    dashboard_url=str(jellyfin.get("url") or ""),
                )

            def collect_jellyfin() -> JellyfinStatus:
                return JellyfinClient(jellyfin, timeout).collect()

            empty = empty_jellyfin
            collect = self.collector_overrides.get(key, collect_jellyfin)
            sources.append(
                _ScheduledSource(
                    key=key,
                    kind="jellyfin",
                    interval=float(jellyfin.get("poll_interval_seconds", default_interval)),
                    collect=collect,
                    empty=empty,
                    current=empty(),
                )
            )
        return sources

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._demo:
            self._ready_event.set()
            return
        if not self._sources:
            self._ready_event.set()
            return
        for source in self._sources:
            source.thread = Thread(
                target=self._worker,
                args=(source,),
                name=f"homelab-monitor-{source.key}",
                daemon=True,
            )
            source.thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        for source in self._sources:
            if source.thread and source.thread.is_alive():
                source.thread.join(timeout=timeout)

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        return self._ready_event.wait(timeout)

    def _worker(self, source: _ScheduledSource) -> None:
        while not self._stop_event.is_set():
            started = monotonic()
            try:
                with self._semaphore:
                    started = monotonic()
                    result = source.collect()
                duration_ms = max(1, round((monotonic() - started) * 1000))
                observed_at = utc_timestamp()
                current = replace(
                    result,
                    observed_at=observed_at,
                    last_success_at=observed_at,
                    consecutive_failure_count=0,
                    probe_duration_ms=duration_ms,
                    freshness=Freshness.FRESH,
                    error=None,
                )
                with self._lock:
                    source.current = current
                    source.last_good = deepcopy(current)
                    source.failures = 0
                delay = source.interval
            except Exception as exc:  # Provider boundary must never stop its worker.
                duration_ms = max(1, round((monotonic() - started) * 1000))
                public_error = classify_provider_error(exc)
                logger.warning("Provider probe %s failed: %s", source.key, exc, exc_info=True)
                with self._lock:
                    source.failures += 1
                    source.current = self._failed_result(
                        source,
                        public_error,
                        duration_ms,
                    )
                    failures = source.failures
                delay = self.retry_delay(source.interval, failures)
            self._update_ready_state()
            self._stop_event.wait(delay)

    def retry_delay(self, interval: float, failures: int) -> float:
        return min(
            interval,
            self._retry_max,
            self._retry_base * (2 ** min(max(0, failures - 1), 10)),
        )

    def _failed_result(
        self,
        source: _ScheduledSource,
        error: ProviderError,
        duration_ms: int,
    ) -> ProviderResult:
        previous = deepcopy(source.last_good) if source.last_good else source.empty()
        return replace(
            previous,
            status=Status.UNAVAILABLE,
            observed_at=utc_timestamp(),
            last_success_at=source.last_good.last_success_at if source.last_good else None,
            consecutive_failure_count=source.failures,
            probe_duration_ms=duration_ms,
            freshness=Freshness.STALE if source.last_good else Freshness.UNKNOWN,
            error=error,
        )

    def _update_ready_state(self) -> None:
        with self._lock:
            if all(source.current.observed_at for source in self._sources):
                self._ready_event.set()

    def _materialize(self, source: _ScheduledSource, now: datetime) -> ProviderResult:
        result = deepcopy(source.current)
        if not result.observed_at or result.freshness != Freshness.FRESH:
            return result
        observed = datetime.fromisoformat(result.observed_at)
        maximum_age = source.interval * 2 + self._freshness_grace
        if (now - observed).total_seconds() <= maximum_age:
            return result
        return replace(
            result,
            status=Status.DEGRADED if result.status == Status.HEALTHY else result.status,
            freshness=Freshness.STALE,
        )

    def snapshot(self) -> Dashboard:
        """Build a response from cached state without running provider I/O."""
        if self._demo:
            dashboard = build_demo_dashboard()
            observed_at = utc_timestamp()
            dashboard.hosts = [
                replace(
                    item,
                    observed_at=observed_at,
                    last_success_at=observed_at,
                    probe_duration_ms=1,
                    freshness=Freshness.FRESH,
                )
                for item in dashboard.hosts
            ]
            dashboard.docker = replace(
                dashboard.docker,
                observed_at=observed_at,
                last_success_at=observed_at,
                probe_duration_ms=1,
                freshness=Freshness.FRESH,
            )
            dashboard.jellyfin = replace(
                dashboard.jellyfin,
                observed_at=observed_at,
                last_success_at=observed_at,
                probe_duration_ms=1,
                freshness=Freshness.FRESH,
            )
            dashboard.generated_at = utc_timestamp()
            return dashboard

        now = datetime.now(UTC)
        with self._lock:
            materialized = [(source, self._materialize(source, now)) for source in self._sources]
        hosts = [result for source, result in materialized if source.kind == "host"]
        docker = next(
            (result for source, result in materialized if source.kind == "docker"),
            DockerStatus(status=Status.UNKNOWN),
        )
        jellyfin = next(
            (result for source, result in materialized if source.kind == "jellyfin"),
            JellyfinStatus(status=Status.UNKNOWN),
        )
        errors = [
            SourceError(
                source=source.key,
                category=result.error.category,
                message=result.error.message,
                observed_at=result.observed_at or utc_timestamp(),
            )
            for source, result in materialized
            if result.error
        ]
        return Dashboard(
            hosts=hosts,
            docker=docker,
            jellyfin=jellyfin,
            errors=errors,
            generated_at=utc_timestamp(),
        )

    def collect(self) -> Dashboard:
        """Compatibility alias for callers migrating from request-time collection."""
        return self.snapshot()
