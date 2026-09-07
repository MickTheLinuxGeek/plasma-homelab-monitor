from pathlib import Path

import pytest
from homelab_monitor.config import ConfigError, load_config


def test_loads_demo_config_without_tokens(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "demo: true\nportainer:\n  enabled: false\njellyfin:\n  enabled: false\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config["demo"] is True
    assert config["request_timeout_seconds"] == 3.0
    assert config["poll_interval_seconds"] == 30.0
    assert config["max_concurrent_probes"] == 4
    assert config["retry_base_seconds"] == 2.0
    assert config["retry_max_seconds"] == 30.0
    assert config["freshness_grace_seconds"] == 5.0
    assert config["history"]["enabled"] is True
    assert config["history"]["retention_days"] == 30
    assert config["history"]["path"].endswith("homelab-monitor/history.sqlite3")
    assert config["notifications"]["enabled"] is False
    assert config["notifications"]["quiet_hours"]["timezone"] == "local"


def test_enabled_provider_requires_environment_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MISSING_PORTAINER_TOKEN", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text(
        "portainer:\n"
        "  enabled: true\n"
        "  url: https://portainer.example.test\n"
        "  api_key_env: MISSING_PORTAINER_TOKEN\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="MISSING_PORTAINER_TOKEN"):
        load_config(path)


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        (
            "notifications:\n  quiet_hours:\n    start: '25:00'\n",
            "24-hour HH:MM",
        ),
        (
            "hosts:\n"
            "  - id: host\n"
            "    probe:\n"
            "      type: tcp\n"
            "      host: 127.0.0.1\n"
            "      port: 22\n"
            "    certificate_thresholds:\n"
            "      warning: 7\n"
            "      critical: 30\n",
            "less than or equal",
        ),
        (
            "hosts:\n"
            "  - id: host\n"
            "    probe:\n"
            "      type: tcp\n"
            "      host: 127.0.0.1\n"
            "      port: 22\n"
            "    metrics:\n"
            "      url: http://metrics.example.test\n",
            "must use https",
        ),
        (
            "hosts:\n"
            "  - id: host\n"
            "    probe:\n"
            "      type: tcp\n"
            "      host: 127.0.0.1\n"
            "      port: 22\n"
            "    metrics:\n"
            "      url: https://metrics.example.test\n"
            "      api_key: literal-secret\n",
            "api_key_env",
        ),
        (
            "portainer:\n  enabled: false\n  endpoint_host_map:\n    1: missing-host\n",
            "unknown host ids",
        ),
    ],
)
def test_rejects_invalid_phase3_configuration(
    tmp_path: Path,
    configuration: str,
    message: str,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(configuration, encoding="utf-8")

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_notifications_require_durable_history(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
history:
  enabled: false
notifications:
  enabled: true
hosts: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="requires history"):
        load_config(config_path)
