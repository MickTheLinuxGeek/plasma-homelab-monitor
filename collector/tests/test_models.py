from homelab_monitor.models import Dashboard, HostStatus, Status


def test_overall_status_is_healthy_when_every_source_is_healthy() -> None:
    dashboard = Dashboard(
        hosts=[
            HostStatus(
                id="host",
                name="Host",
                status=Status.HEALTHY,
                detail="Online",
            )
        ]
    )

    assert dashboard.overall_status() == Status.HEALTHY


def test_mixed_host_statuses_degrade_dashboard() -> None:
    dashboard = Dashboard(
        hosts=[
            HostStatus("one", "One", Status.HEALTHY, "Online"),
            HostStatus("two", "Two", Status.UNAVAILABLE, "Offline"),
        ]
    )

    payload = dashboard.to_dict()

    assert payload["overall_status"] == "degraded"
    assert payload["summary"]["healthy"] == 1
    assert payload["summary"]["unavailable"] == 1
