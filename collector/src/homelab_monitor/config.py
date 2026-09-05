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


def _positive_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be numeric") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return number


def _private_environment_file(path: Path) -> None:
    if path.exists() and path.stat().st_mode & 0o077:
        raise ConfigError(f"{path} must not be readable or writable by group or other users")


def _normalize_tls(config: dict[str, Any], name: str, base_directory: Path) -> None:
    config.setdefault("verify_tls", True)
    config.setdefault("allow_insecure_tls", False)
    if not isinstance(config["verify_tls"], bool):
        raise ConfigError(f"{name}.verify_tls must be true or false")
    if not config["verify_tls"] and not config["allow_insecure_tls"]:
        raise ConfigError(
            f"{name}.verify_tls=false requires allow_insecure_tls=true; configure ca_bundle instead"
        )
    ca_bundle = config.get("ca_bundle")
    if ca_bundle:
        if not config["verify_tls"]:
            raise ConfigError(f"{name}.ca_bundle cannot be used when TLS verification is disabled")
        path = Path(str(ca_bundle)).expanduser()
        if not path.is_absolute():
            path = base_directory / path
        if not path.is_file():
            raise ConfigError(f"{name}.ca_bundle does not exist or is not a file")
        config["ca_bundle"] = str(path.resolve())


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration and resolve token environment variables."""
    config_path = Path(path or os.getenv("HOMELAB_MONITOR_CONFIG", "config.yaml"))
    if not config_path.exists():
        raise ConfigError(
            f"Configuration file not found: {config_path}. Copy config.example.yaml to config.yaml."
        )
    environment_path = config_path.resolve().parent / ".env"
    _private_environment_file(environment_path)
    if environment_path.exists():
        load_dotenv(environment_path)

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = _require_mapping(raw, "configuration")
    config.setdefault("demo", False)
    config.setdefault("request_timeout_seconds", 3)
    config.setdefault("poll_interval_seconds", 30)
    config.setdefault("max_concurrent_probes", 4)
    config.setdefault("retry_base_seconds", 2)
    config.setdefault("retry_max_seconds", 30)
    config.setdefault("freshness_grace_seconds", 5)
    config.setdefault("hosts", [])

    for setting in (
        "request_timeout_seconds",
        "poll_interval_seconds",
        "retry_base_seconds",
        "retry_max_seconds",
        "freshness_grace_seconds",
    ):
        config[setting] = _positive_number(config[setting], setting)
    try:
        config["max_concurrent_probes"] = int(config["max_concurrent_probes"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("max_concurrent_probes must be an integer") from exc
    if config["max_concurrent_probes"] < 1:
        raise ConfigError("max_concurrent_probes must be at least one")
    if config["retry_max_seconds"] < config["retry_base_seconds"]:
        raise ConfigError("retry_max_seconds must be greater than or equal to retry_base_seconds")

    if not isinstance(config["hosts"], list):
        raise ConfigError("hosts must be a list")
    host_ids: set[str] = set()
    for index, raw_host in enumerate(config["hosts"]):
        host = _require_mapping(raw_host, f"hosts[{index}]")
        host_id = str(host.get("id") or host.get("name") or index)
        if host_id in host_ids:
            raise ConfigError(f"duplicate host id: {host_id}")
        host_ids.add(host_id)
        host["id"] = host_id
        host["poll_interval_seconds"] = _positive_number(
            host.get("poll_interval_seconds", config["poll_interval_seconds"]),
            f"hosts[{index}].poll_interval_seconds",
        )
        host["timeout_seconds"] = _positive_number(
            host.get("timeout_seconds", config["request_timeout_seconds"]),
            f"hosts[{index}].timeout_seconds",
        )
        probe = _require_mapping(host.get("probe"), f"hosts[{index}].probe")
        if probe.get("type") not in {"http", "tcp"}:
            raise ConfigError(f"hosts[{index}].probe.type must be 'http' or 'tcp'")
        if probe["type"] == "http":
            _normalize_tls(probe, f"hosts[{index}].probe", config_path.resolve().parent)
        host["probe"] = probe

    for provider_name in ("portainer", "jellyfin"):
        provider = _require_mapping(config.get(provider_name), provider_name)
        provider.setdefault("enabled", False)
        provider["poll_interval_seconds"] = _positive_number(
            provider.get("poll_interval_seconds", config["poll_interval_seconds"]),
            f"{provider_name}.poll_interval_seconds",
        )
        provider["timeout_seconds"] = _positive_number(
            provider.get("timeout_seconds", config["request_timeout_seconds"]),
            f"{provider_name}.timeout_seconds",
        )
        _normalize_tls(provider, provider_name, config_path.resolve().parent)
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
