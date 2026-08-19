from typing import Any

from homelab_monitor.app import create_app


def test_health_endpoint(demo_config: dict[str, Any]) -> None:
    client = create_app(config=demo_config).test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_demo_dashboard_contract(demo_config: dict[str, Any]) -> None:
    client = create_app(config=demo_config).test_client()

    response = client.get("/api/v1/dashboard")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["schema_version"] == "1"
    assert payload["overall_status"] == "degraded"
    assert len(payload["hosts"]) == 3
    assert payload["docker"]["environments"][0]["running"] == 8
    assert payload["jellyfin"]["active_sessions"][0]["item_name"] == "Demo Movie"
