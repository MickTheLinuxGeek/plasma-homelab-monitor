from copy import deepcopy
from typing import Any

from homelab_monitor.app import create_app
from jsonschema import Draft202012Validator


def test_health_endpoint(demo_config: dict[str, Any]) -> None:
    client = create_app(config=demo_config).test_client()
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "api_version": "2",
        "collector_version": "0.3.0",
    }


def test_demo_dashboard_v2_contract(demo_config: dict[str, Any]) -> None:
    client = create_app(config=demo_config).test_client()

    response = client.get("/api/v2/dashboard")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["schema_version"] == "2"
    assert payload["api_version"] == "2"
    assert payload["collector_version"] == "0.3.0"
    assert payload["generated_at"]
    assert payload["last_successful_observation_at"]
    assert payload["overall_status"] == "degraded"
    assert len(payload["hosts"]) == 3
    assert payload["docker"]["environments"][0]["running"] == 8
    assert payload["jellyfin"]["active_sessions"][0]["item_name"] == "Demo Movie"
    assert payload["docker"]["observed_at"]
    assert payload["docker"]["last_success_at"]
    assert payload["docker"]["freshness"] == "fresh"
    assert payload["docker"]["consecutive_failure_count"] == 0
    assert payload["docker"]["probe_duration_ms"] == 1


def test_v1_dashboard_remains_compatible(demo_config: dict[str, Any]) -> None:
    payload = create_app(config=demo_config).test_client().get("/api/v1/dashboard").get_json()

    assert payload["schema_version"] == "1"
    assert payload["api_version"] == "1"
    assert isinstance(payload["docker"]["error"], str | type(None))
    assert "freshness" not in payload["docker"]
    assert "error" not in payload["hosts"][0]


def test_published_schema_accepts_dashboard_and_rejects_missing_provider_state(
    demo_config: dict[str, Any],
) -> None:
    client = create_app(config=demo_config).test_client()
    schema = client.get("/api/v2/schema").get_json()
    payload = client.get("/api/v2/dashboard").get_json()
    validator = Draft202012Validator(schema)

    assert not list(validator.iter_errors(payload))

    malformed = deepcopy(payload)
    del malformed["hosts"][0]["freshness"]
    assert list(validator.iter_errors(malformed))
