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
