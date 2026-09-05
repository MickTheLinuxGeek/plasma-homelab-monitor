"""Read-only Portainer API adapter."""

from __future__ import annotations

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


class PortainerClient:
    def __init__(
        self,
        config: dict[str, Any],
        timeout: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.base_url = str(config["url"]).rstrip("/")
        self.endpoint_ids = {int(value) for value in config.get("endpoint_ids", [])}
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

    @staticmethod
    def _container(item: dict[str, Any]) -> ContainerStatus:
        if not isinstance(item, dict):
            raise MalformedResponseError("Portainer container entry must be an object")
        state = str(item.get("State", "unknown")).lower()
        detail = str(item.get("Status", state.title()))
        healthy = state == "running" and "(unhealthy)" not in detail.lower()
        status = (
            Status.HEALTHY
            if healthy
            else (Status.DEGRADED if state == "running" else Status.UNAVAILABLE)
        )
        names = item.get("Names") or []
        name = str(names[0]).lstrip("/") if names else str(item.get("Id", "unknown"))[:12]
        return ContainerStatus(
            id=str(item.get("Id", "")),
            name=name,
            image=str(item.get("Image", "")),
            state=state,
            status=status,
            detail=detail,
        )

    def collect(self) -> DockerStatus:
        try:
            endpoints = self._get("/api/endpoints")
            if not isinstance(endpoints, list):
                raise MalformedResponseError("Portainer endpoints response must be a list")
            environments: list[DockerEnvironment] = []
            for endpoint in endpoints:
                if not isinstance(endpoint, dict):
                    raise MalformedResponseError("Portainer endpoint entry must be an object")
                endpoint_id = int(endpoint["Id"])
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
                        )
                    )
                    continue

                raw_containers = self._get(
                    f"/api/endpoints/{endpoint_id}/docker/containers/json",
                    all="true",
                )
                if not isinstance(raw_containers, list):
                    raise MalformedResponseError("Portainer containers response must be a list")
                containers = [self._container(item) for item in raw_containers]
                running = sum(item.state == "running" for item in containers)
                total = len(containers)
                stopped = total - running
                if total == 0 or running == total:
                    status = Status.HEALTHY
                elif running == 0:
                    status = Status.UNAVAILABLE
                else:
                    status = Status.DEGRADED
                environments.append(
                    DockerEnvironment(
                        id=endpoint_id,
                        name=name,
                        status=status,
                        running=running,
                        stopped=stopped,
                        total=total,
                        containers=containers,
                    )
                )

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
