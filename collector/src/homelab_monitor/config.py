"""Configuration loading and validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when collector configuration is invalid."""


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration and resolve token environment variables."""
    load_dotenv()
    config_path = Path(path or os.getenv("HOMELAB_MONITOR_CONFIG", "config.yaml"))
    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found: {config_path}. Copy config.example.yaml to config.yaml."
        )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = _require_mapping(raw, "configuration")
    config.setdefault("demo", False)
    config.setdefault("request_timeout_seconds", 3)
    config.setdefault("hosts", [])

    try:
        timeout = float(config["request_timeout_seconds"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("request_timeout_seconds must be numeric") from exc
    if timeout <= 0:
        raise ConfigError("request_timeout_seconds must be greater than zero")
    config["request_timeout_seconds"] = timeout

    if not isinstance(config["hosts"], list):
        raise ConfigError("hosts must be a list")

    for provider_name in ("portainer", "jellyfin"):
        provider = _require_mapping(config.get(provider_name), provider_name)
        provider.setdefault("enabled", False)
        provider.setdefault("verify_tls", True)
        if provider["enabled"]:
            if not provider.get("url"):
                raise ConfigError(f"{provider_name}.url is required when enabled")
            env_name = provider.get("api_key_env")
            if not env_name:
                raise ConfigError(f"{provider_name}.api_key_env is required when enabled")
            token = os.getenv(str(env_name))
            if not token:
                raise ConfigError(f"Environment variable {env_name} is required by {provider_name}")
            provider["api_key"] = token
        config[provider_name] = provider

    return config
