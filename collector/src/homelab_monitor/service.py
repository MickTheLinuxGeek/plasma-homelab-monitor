"""Background collection and cached dashboard snapshots."""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Semaphore, Thread
from time import monotonic
from typing import Any

from homelab_monitor.contracts import Clock, NotificationSink
from homelab_monitor.demo import build_demo_dashboard
from homelab_monitor.errors import classify_provider_error
from homelab_monitor.events import IncidentEngine, TransitionPolicy
from homelab_monitor.history import (
    BootObservation,
    HistoryCoordinator,
    HistoryLimits,
    HistoryStore,
    Observation,
    UtcClock,
)
from homelab_monitor.models import (
    Dashboard,
    DockerStatus,
    FeatureStatus,
    Freshness,
    HostMetricsStatus,
    HostStatus,
    JellyfinStatus,
    ProviderError,
    SourceError,
    Status,
    utc_timestamp,
)
from homelab_monitor.notifications import (
    JeepneyNotificationSink,
    NotificationDispatcher,
    QuietHours,
)
from homelab_monitor.providers import (
    HostMetricsClient,
    InspectCacheEntry,
    JellyfinClient,
    PortainerClient,
    probe_host,
)

logger = logging.getLogger(__name__)
ProviderResult = HostStatus | HostMetricsStatus | DockerStatus | JellyfinStatus


@dataclass(slots=True)
class _ScheduledSource:
    key: str
    kind: str
    interval: float
    collect: Callable[[], ProviderResult]
    empty: Callable[[], ProviderResult]
    current: ProviderResult
    target_id: str | None = None
    source_config: dict[str, Any] | None = None
    last_good: ProviderResult | None = None
    failures: int = 0
    thread: Thread | None = None


class DashboardService:
    """Poll providers independently and serve immutable cached snapshots."""

    def __init__(
        self,
        config: dict[str, Any],
        collector_overrides: dict[str, Callable[[], ProviderResult]] | None = None,
        *,
        clock: Clock | None = None,
        notification_sink: NotificationSink | None = None,
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
        self._closed = False
        self._demo = bool(config.get("demo"))
        self._clock = clock or UtcClock()
        self._portainer_inspect_cache: dict[tuple[int, str], InspectCacheEntry] = {}
        self._history_store: HistoryStore | None = None
        self._history: HistoryCoordinator | None = None
        self._incident_engine: IncidentEngine | None = None
        self._notification_dispatcher: NotificationDispatcher | None = None
        self._notification_sink = notification_sink
        self._notification_thread: Thread | None = None
        self._sources = self._build_sources()
        if not self._demo and bool(config.get("history", {}).get("enabled", False)):
            self._configure_history()

    def _configure_history(self) -> None:
        history_config = self.config["history"]
        notification_config = self.config.get("notifications", {})
        store = HistoryStore(
            history_config.get("path", ":memory:"),
            limits=HistoryLimits.from_config(history_config),
        )
        self._history_store = store
        self._incident_engine = IncidentEngine(
            store,
            policy=TransitionPolicy.from_config(notification_config),
            clock=self._clock,
            correlation_window=timedelta(
                seconds=float(self.config.get("event_correlation_window_seconds", 120))
            ),
        )
        if notification_config.get("enabled", False):
            sink = self._notification_sink or JeepneyNotificationSink()
            self._notification_sink = sink
            self._notification_dispatcher = NotificationDispatcher(
                store,
                sink,
                clock=self._clock,
                quiet_hours=QuietHours.from_config(notification_config.get("quiet_hours", {})),
                queue_size=int(notification_config.get("queue_size", 64)),
                retry_limit=int(notification_config.get("retry_limit", 3)),
            )
        self._history = HistoryCoordinator(
            store,
            handler=self._process_history_observation,
            queue_size=int(history_config.get("queue_size", 512)),
            clock=self._clock,
        )

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
                    target_id=host_id,
                    source_config=host,
                )
            )
            metrics = host.get("metrics", {})
            if metrics.get("enabled"):
                metrics_key = f"metrics:{host_id}"
                metrics_timeout = float(metrics.get("timeout_seconds", timeout))

                def empty_metrics() -> HostMetricsStatus:
                    return HostMetricsStatus(status=Status.UNKNOWN)

                def collect_metrics(
                    metrics: dict[str, Any] = metrics,
                    timeout: float = metrics_timeout,
                ) -> HostMetricsStatus:
                    return HostMetricsClient(metrics, timeout).collect()

                metrics_empty = empty_metrics
                metrics_collect = self.collector_overrides.get(metrics_key, collect_metrics)
                sources.append(
                    _ScheduledSource(
                        key=metrics_key,
                        kind="host_metrics",
                        interval=float(
                            metrics.get("poll_interval_seconds", host["poll_interval_seconds"])
                        ),
                        collect=metrics_collect,
                        empty=metrics_empty,
                        current=metrics_empty(),
                        target_id=host_id,
                        source_config=host,
                    )
                )

        portainer = self.config.get("portainer", {})
        if portainer.get("enabled"):
            key = "portainer"
            timeout = float(portainer.get("timeout_seconds", default_timeout))

            def empty_portainer() -> DockerStatus:
                return DockerStatus(status=Status.UNKNOWN)

            def collect_portainer() -> DockerStatus:
                return PortainerClient(
                    portainer,
                    timeout,
                    inspect_cache=self._portainer_inspect_cache,
                ).collect()

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
                    source_config=portainer,
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
                    source_config=jellyfin,
                )
            )
        return sources

    def start(self) -> None:
        if self._started:
            return
        if self._closed:
            raise RuntimeError("DashboardService cannot be restarted after it is closed")
        self._started = True
        if self._demo:
            self._ready_event.set()
            return
        if self._notification_dispatcher:
            self._notification_dispatcher.start()
        if self._history:
            self._history.start()
        if self._notification_dispatcher:
            self._notification_thread = Thread(
                target=self._notification_loop,
                name="homelab-monitor-notification-tick",
                daemon=True,
            )
            self._notification_thread.start()
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
        if self._closed:
            return
        self._stop_event.set()
        for source in self._sources:
            if source.thread and source.thread.is_alive():
                source.thread.join(timeout=timeout)
        if self._notification_thread and self._notification_thread.is_alive():
            self._notification_thread.join(timeout=timeout)
        if self._history:
            self._history.stop(timeout)
        if self._notification_dispatcher:
            self._notification_dispatcher.dispatch_due()
            self._notification_dispatcher.stop(timeout)
        close_sink = getattr(self._notification_sink, "close", None)
        if close_sink:
            close_sink()
        if self._history_store:
            self._history_store.close()
        self._closed = True

    def _notification_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            if self._notification_dispatcher:
                self._notification_dispatcher.dispatch_due()

    def _process_history_observation(
        self,
        observation: Observation | BootObservation,
    ) -> None:
        if isinstance(observation, BootObservation):
            if self._history_store:
                self._history_store.record_boot_observation(observation)
        elif self._incident_engine:
            self._incident_engine.process(observation)
        if self._notification_dispatcher:
            self._notification_dispatcher.dispatch_due()

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
                observed_at = (
                    result.observed_at
                    if isinstance(result, HostMetricsStatus) and result.observed_at
                    else utc_timestamp()
                )
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
                    current = self._failed_result(
                        source,
                        public_error,
                        duration_ms,
                    )
                    source.current = current
                    failures = source.failures
                delay = self.retry_delay(source.interval, failures)
            self._submit_source_observations(source, current)
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
        if isinstance(previous, HostMetricsStatus):
            previous.measurements = [
                replace(measurement, freshness=Freshness.STALE)
                for measurement in previous.measurements
            ]
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

    @staticmethod
    def _observation_time(value: str | None) -> datetime:
        if not value:
            return datetime.now(UTC)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)

    def _submit_history(self, observation: Observation | BootObservation) -> None:
        if self._history and not self._history.submit(observation):
            resource_id = (
                observation.resource_id
                if isinstance(observation, Observation)
                else f"host:{observation.host_id}:boot"
            )
            logger.warning("History queue full; dropped observation for %s", resource_id)

    def _submit_source_observations(
        self,
        source: _ScheduledSource,
        result: ProviderResult,
    ) -> None:
        if not self._history:
            return
        observed_at = self._observation_time(result.observed_at)
        if source.kind == "host" and isinstance(result, HostStatus):
            reachability = Status.UNAVAILABLE if result.error else Status.HEALTHY
            self._submit_history(
                Observation(
                    resource_id=source.key,
                    resource_name=result.name,
                    status=reachability,
                    observed_at=observed_at,
                    metric="latency_ms",
                    value=result.latency_ms,
                    unit="ms",
                )
            )
            if result.error is None and result.certificate_days_remaining is not None:
                thresholds = (source.source_config or {}).get("certificate_thresholds", {})
                days = result.certificate_days_remaining
                if days <= float(thresholds.get("critical", 7)):
                    certificate_status = Status.UNAVAILABLE
                elif days <= float(thresholds.get("warning", 30)):
                    certificate_status = Status.DEGRADED
                else:
                    certificate_status = Status.HEALTHY
                self._submit_history(
                    Observation(
                        resource_id=f"{source.key}:certificate",
                        resource_name=f"{result.name} certificate",
                        status=certificate_status,
                        observed_at=observed_at,
                        metric="certificate_days_remaining",
                        value=days,
                        unit="days",
                    )
                )
            return

        if source.kind == "host_metrics" and isinstance(result, HostMetricsStatus):
            host_id = source.target_id or source.key.removeprefix("metrics:")
            host_name = str((source.source_config or {}).get("name") or host_id)
            self._submit_history(
                Observation(
                    resource_id=source.key,
                    resource_name=f"{host_name} metrics",
                    status=Status.UNAVAILABLE if result.error else Status.HEALTHY,
                    observed_at=observed_at,
                )
            )
            if result.error is not None:
                return
            if result.boot_id:
                self._submit_history(
                    BootObservation(
                        host_id=host_id,
                        host_name=host_name,
                        boot_id=result.boot_id,
                        observed_at=observed_at,
                    )
                )
            for measurement in result.measurements:
                measurement_time = self._observation_time(measurement.observed_at)
                numeric_value = (
                    measurement.value
                    if isinstance(measurement.value, (int, float))
                    and not isinstance(measurement.value, bool)
                    else None
                )
                sustained_samples = (
                    measurement.thresholds.sustained_samples
                    if measurement.thresholds is not None
                    else 1
                )
                self._submit_history(
                    Observation(
                        resource_id=f"{source.key}:{measurement.id}",
                        resource_name=f"{host_name} · {measurement.label}",
                        status=measurement.status,
                        observed_at=measurement_time,
                        metric=measurement.kind,
                        value=numeric_value,
                        unit=measurement.unit,
                        sustained_samples=sustained_samples,
                    )
                )
            return

        if source.kind == "docker" and isinstance(result, DockerStatus):
            self._submit_history(
                Observation(
                    resource_id=source.key,
                    resource_name="Portainer",
                    status=Status.UNAVAILABLE if result.error else Status.HEALTHY,
                    observed_at=observed_at,
                )
            )
            if result.error is not None:
                return
            for environment in result.environments:
                parent_resource_id = f"host:{environment.host_id}" if environment.host_id else None
                self._submit_history(
                    Observation(
                        resource_id=f"docker:environment:{environment.id}",
                        resource_name=environment.name,
                        status=environment.status,
                        observed_at=observed_at,
                        parent_resource_id=parent_resource_id,
                    )
                )
                for container in environment.containers:
                    self._submit_history(
                        Observation(
                            resource_id=f"docker:container:{environment.id}:{container.id}",
                            resource_name=container.name,
                            status=container.status,
                            observed_at=observed_at,
                            parent_resource_id=parent_resource_id,
                        )
                    )
            return

        if source.kind == "jellyfin" and isinstance(result, JellyfinStatus):
            host_id = (source.source_config or {}).get("host_id")
            self._submit_history(
                Observation(
                    resource_id=source.key,
                    resource_name=result.server_name or "Jellyfin",
                    status=result.status,
                    observed_at=observed_at,
                    parent_resource_id=f"host:{host_id}" if host_id else None,
                )
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
        if isinstance(result, HostMetricsStatus):
            result.measurements = [
                replace(measurement, freshness=Freshness.STALE)
                for measurement in result.measurements
            ]
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

        now = self._clock.now().astimezone(UTC)
        with self._lock:
            materialized = [(source, self._materialize(source, now)) for source in self._sources]
        metrics_by_host = {
            source.target_id: result
            for source, result in materialized
            if source.kind == "host_metrics" and source.target_id
        }
        hosts = [
            replace(result, metrics=metrics_by_host.get(source.target_id))
            for source, result in materialized
            if source.kind == "host"
        ]
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
        dashboard = Dashboard(
            hosts=hosts,
            docker=docker,
            jellyfin=jellyfin,
            errors=errors,
            generated_at=utc_timestamp(),
        )
        history_config = self.config.get("history", {})
        history_enabled = bool(history_config.get("enabled", False))
        if self._history:
            history_model = self._history.cache.snapshot()
            dashboard.recent_events = list(history_model.recent_events)
            dashboard.trends = list(history_model.trends)
        dashboard.features = FeatureStatus(
            history_enabled=history_enabled,
            history_available=self._history is not None,
            history_retention_days=(
                int(history_config.get("retention_days", 30)) if history_enabled else 0
            ),
            notifications_enabled=bool(self.config.get("notifications", {}).get("enabled", False)),
        )
        return dashboard

    def collect(self) -> Dashboard:
        """Compatibility alias for callers migrating from request-time collection."""
        return self.snapshot()
