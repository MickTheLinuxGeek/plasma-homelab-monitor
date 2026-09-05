"""Dashboard aggregation service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from homelab_monitor.demo import build_demo_dashboard
from homelab_monitor.models import (
    Dashboard,
    DockerStatus,
    JellyfinStatus,
    SourceError,
    Status,
    utc_timestamp,
)
from homelab_monitor.providers import JellyfinClient, PortainerClient, probe_host


class DashboardService:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.timeout = float(config["request_timeout_seconds"])

    def collect(self) -> Dashboard:
        if self.config.get("demo"):
            dashboard = build_demo_dashboard()
            dashboard.generated_at = utc_timestamp()
            return dashboard

        dashboard = Dashboard()
        futures: dict[Any, tuple[str, str | None]] = {}
        host_order = {
            str(host.get("id") or host.get("name") or index): index
            for index, host in enumerate(self.config.get("hosts", []))
        }

        with ThreadPoolExecutor(max_workers=max(1, len(host_order) + 2)) as executor:
            for host in self.config.get("hosts", []):
                host_id = str(host.get("id") or host.get("name") or "host")
                futures[executor.submit(probe_host, host, self.timeout)] = ("host", host_id)

            portainer = self.config["portainer"]
            if portainer.get("enabled"):
                futures[executor.submit(PortainerClient(portainer, self.timeout).collect)] = (
                    "portainer",
                    None,
                )

            jellyfin = self.config["jellyfin"]
            if jellyfin.get("enabled"):
                futures[executor.submit(JellyfinClient(jellyfin, self.timeout).collect)] = (
                    "jellyfin",
                    None,
                )

            for future in as_completed(futures):
                source, _ = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # Defensive boundary around provider integrations.
                    dashboard.errors.append(SourceError(source=source, message=str(exc)))
                    continue

                if source == "host":
                    dashboard.hosts.append(result)
                elif source == "portainer":
                    dashboard.docker = result
                    if result.error:
                        dashboard.errors.append(
                            SourceError(source="portainer", message=result.error)
                        )
                elif source == "jellyfin":
                    dashboard.jellyfin = result
                    if result.error:
                        dashboard.errors.append(
                            SourceError(source="jellyfin", message=result.error)
                        )

        dashboard.hosts.sort(key=lambda item: host_order.get(item.id, len(host_order)))
        if not self.config["portainer"].get("enabled"):
            dashboard.docker = DockerStatus(status=Status.UNKNOWN)
        if not self.config["jellyfin"].get("enabled"):
            dashboard.jellyfin = JellyfinStatus(status=Status.UNKNOWN)
        dashboard.generated_at = utc_timestamp()
        return dashboard
