"""Deterministic demo data for widget development."""

from datetime import UTC, datetime, timedelta

from homelab_monitor.models import (
    ContainerStatus,
    Dashboard,
    DockerEnvironment,
    DockerStatus,
    FeatureStatus,
    Freshness,
    HostMetricsStatus,
    HostStatus,
    JellyfinSession,
    JellyfinStatus,
    Measurement,
    Severity,
    Status,
    ThresholdDefinition,
    ThresholdDirection,
    TimelineEvent,
    TrendPoint,
    TrendSeries,
)


def build_demo_dashboard() -> Dashboard:
    now = datetime.now(UTC)

    def timestamp(minutes_ago: int = 0) -> str:
        return (now - timedelta(minutes=minutes_ago)).isoformat(timespec="milliseconds")

    return Dashboard(
        hosts=[
            HostStatus(
                id="dxp2800",
                name="DXP2800",
                status=Status.HEALTHY,
                detail="Online · OpenMediaVault",
                dashboard_url="https://openmediavault.example.test",
                latency_ms=12,
                certificate_expires_at=(now + timedelta(days=82)).isoformat(
                    timespec="milliseconds"
                ),
                certificate_days_remaining=82,
                metrics=HostMetricsStatus(
                    status=Status.HEALTHY,
                    boot_id="demo-dxp2800-boot",
                    observed_at=timestamp(),
                    last_success_at=timestamp(),
                    freshness=Freshness.FRESH,
                    measurements=[
                        Measurement(
                            id="disk_used_percent",
                            label="Data disk",
                            kind="disk",
                            status=Status.HEALTHY,
                            value=61.4,
                            unit="%",
                            detail="61.4% used",
                            thresholds=ThresholdDefinition(
                                direction=ThresholdDirection.ABOVE,
                                warning=80,
                                critical=90,
                            ),
                            observed_at=timestamp(),
                            freshness=Freshness.FRESH,
                        ),
                        Measurement(
                            id="temperature_c",
                            label="System temperature",
                            kind="temperature",
                            status=Status.HEALTHY,
                            value=42,
                            unit="°C",
                            detail="Within threshold",
                            thresholds=ThresholdDefinition(
                                direction=ThresholdDirection.ABOVE,
                                warning=70,
                                critical=85,
                            ),
                            observed_at=timestamp(),
                            freshness=Freshness.FRESH,
                        ),
                    ],
                ),
            ),
            HostStatus(
                id="dxp4800p",
                name="DXP4800 Plus",
                status=Status.HEALTHY,
                detail="Online · Forgejo",
                dashboard_url="https://forgejo.example.test",
                latency_ms=9,
                certificate_expires_at=(now + timedelta(days=21)).isoformat(
                    timespec="milliseconds"
                ),
                certificate_days_remaining=21,
            ),
            HostStatus(
                id="jellyfin",
                name="Jellyfin Host",
                status=Status.DEGRADED,
                detail="Online · storage check pending",
                dashboard_url="https://jellyfin.example.test",
                latency_ms=18,
                metrics=HostMetricsStatus(
                    status=Status.DEGRADED,
                    boot_id="demo-jellyfin-boot",
                    observed_at=timestamp(),
                    last_success_at=timestamp(),
                    freshness=Freshness.FRESH,
                    measurements=[
                        Measurement(
                            id="backup_age_hours",
                            label="Media backup",
                            kind="backup",
                            status=Status.DEGRADED,
                            value=31,
                            unit="h",
                            detail="Last successful backup was 31 hours ago",
                            thresholds=ThresholdDefinition(
                                direction=ThresholdDirection.ABOVE,
                                warning=24,
                                critical=48,
                            ),
                            observed_at=timestamp(),
                            freshness=Freshness.FRESH,
                        ),
                        Measurement(
                            id="memory_used_percent",
                            label="Memory",
                            kind="memory",
                            status=Status.HEALTHY,
                            value=58,
                            unit="%",
                            detail="58% used",
                            thresholds=ThresholdDefinition(
                                direction=ThresholdDirection.ABOVE,
                                warning=85,
                                critical=95,
                                sustained_samples=3,
                            ),
                            observed_at=timestamp(),
                            freshness=Freshness.FRESH,
                        ),
                    ],
                ),
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
                    host_id="dxp2800",
                    containers=[
                        ContainerStatus(
                            id="gitea-demo",
                            name="gitea",
                            image="gitea/gitea:latest",
                            state="running",
                            status=Status.HEALTHY,
                            detail="Up 6 days",
                            health="healthy",
                            restart_count=0,
                            project="forgejo",
                        ),
                        ContainerStatus(
                            id="wikidocs-demo",
                            name="wikidocs",
                            image="requarks/wiki:latest",
                            state="exited",
                            status=Status.UNAVAILABLE,
                            detail="Exited (1) 14 minutes ago",
                            exit_code=1,
                            finished_at=timestamp(14),
                            recent_exit=True,
                            project="docs",
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
        recent_events=[
            TimelineEvent(
                id=2,
                resource_id="host:jellyfin:backup_age_hours",
                resource_name="Jellyfin Host · Media backup",
                event_type="threshold_breached",
                severity=Severity.WARNING,
                message="Backup age crossed the 24 hour warning threshold.",
                occurred_at=timestamp(31),
                previous_status=Status.HEALTHY,
                current_status=Status.DEGRADED,
                incident_id=2,
            ),
            TimelineEvent(
                id=1,
                resource_id="container:wikidocs-demo",
                resource_name="wikidocs",
                event_type="status_changed",
                severity=Severity.CRITICAL,
                message="Container exited with code 1.",
                occurred_at=timestamp(14),
                previous_status=Status.HEALTHY,
                current_status=Status.UNAVAILABLE,
                incident_id=1,
            ),
        ],
        trends=[
            TrendSeries(
                resource_id="host:dxp2800:disk_used_percent",
                label="DXP2800 · Data disk",
                metric="disk_used_percent",
                unit="%",
                points=[
                    TrendPoint(observed_at=timestamp(120), status=Status.HEALTHY, value=60.8),
                    TrendPoint(observed_at=timestamp(60), status=Status.HEALTHY, value=61.1),
                    TrendPoint(observed_at=timestamp(), status=Status.HEALTHY, value=61.4),
                ],
            ),
            TrendSeries(
                resource_id="host:jellyfin:backup_age_hours",
                label="Jellyfin Host · Media backup",
                metric="backup_age_hours",
                unit="h",
                points=[
                    TrendPoint(observed_at=timestamp(120), status=Status.HEALTHY, value=29),
                    TrendPoint(observed_at=timestamp(60), status=Status.DEGRADED, value=30),
                    TrendPoint(observed_at=timestamp(), status=Status.DEGRADED, value=31),
                ],
            ),
        ],
        features=FeatureStatus(
            history_enabled=True,
            history_available=True,
            history_retention_days=30,
            notifications_enabled=False,
        ),
    )
