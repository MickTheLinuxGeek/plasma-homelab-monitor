"""Deterministic demo data for widget development."""

from homelab_monitor.models import (
    ContainerStatus,
    Dashboard,
    DockerEnvironment,
    DockerStatus,
    HostStatus,
    JellyfinSession,
    JellyfinStatus,
    Status,
)


def build_demo_dashboard() -> Dashboard:
    return Dashboard(
        hosts=[
            HostStatus(
                id="dxp2800",
                name="DXP2800",
                status=Status.HEALTHY,
                detail="Online · OpenMediaVault",
                dashboard_url="https://openmediavault.example.test",
                latency_ms=12,
            ),
            HostStatus(
                id="dxp4800p",
                name="DXP4800 Plus",
                status=Status.HEALTHY,
                detail="Online · Forgejo",
                dashboard_url="https://forgejo.example.test",
                latency_ms=9,
            ),
            HostStatus(
                id="jellyfin",
                name="Jellyfin Host",
                status=Status.DEGRADED,
                detail="Online · storage check pending",
                dashboard_url="https://jellyfin.example.test",
                latency_ms=18,
            ),
        ],
        docker=DockerStatus(
            status=Status.DEGRADED,
            environments=[
                DockerEnvironment(
                    id=1,
                    name="DXP2800 Docker",
                    status=Status.DEGRADED,
                    running=8,
                    stopped=1,
                    total=9,
                    containers=[
                        ContainerStatus(
                            id="gitea-demo",
                            name="gitea",
                            image="gitea/gitea:latest",
                            state="running",
                            status=Status.HEALTHY,
                            detail="Up 6 days",
                        ),
                        ContainerStatus(
                            id="wikidocs-demo",
                            name="wikidocs",
                            image="requarks/wiki:latest",
                            state="exited",
                            status=Status.UNAVAILABLE,
                            detail="Exited (1) 14 minutes ago",
                        ),
                    ],
                )
            ],
        ),
        jellyfin=JellyfinStatus(
            status=Status.HEALTHY,
            server_name="Jellyfin",
            version="10.x",
            dashboard_url="https://jellyfin.example.test",
            active_sessions=[
                JellyfinSession(
                    user_name="Demo User",
                    client="Jellyfin Web",
                    device_name="Living Room",
                    item_name="Demo Movie",
                )
            ],
        ),
    )
