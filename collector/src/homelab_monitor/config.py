"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def _positive_integer(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if number < 1:
        raise ConfigError(f"{name} must be at least one")
    return number


def _nonnegative_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be numeric") from exc
    if number < 0:
        raise ConfigError(f"{name} must not be negative")
    return number


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false")
    return value


def _clock_time(value: Any, name: str) -> str:
    text = str(value)
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
        raise ConfigError(f"{name} must use 24-hour HH:MM format")
    return text


def _state_path(value: Any, config_path: Path) -> str:
    default_root = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
    raw_path = Path(str(value or default_root / "homelab-monitor" / "history.sqlite3")).expanduser()
    path = raw_path if raw_path.is_absolute() else config_path.resolve().parent / raw_path
    path = path.resolve()
    if path == Path(path.anchor) or (path.exists() and path.is_dir()):
        raise ConfigError("history.path must identify a database file")
    return str(path)


def _thresholds(
    value: Any,
    name: str,
    *,
    direction: str,
    default_warning: float,
    default_critical: float,
    default_sustained_samples: int = 1,
) -> dict[str, Any]:
    config = _require_mapping(value, name)
    config.setdefault("direction", direction)
    config.setdefault("warning", default_warning)
    config.setdefault("critical", default_critical)
    config.setdefault("sustained_samples", default_sustained_samples)
    if config["direction"] not in {"above", "below"}:
        raise ConfigError(f"{name}.direction must be 'above' or 'below'")
    config["warning"] = _nonnegative_number(config["warning"], f"{name}.warning")
    config["critical"] = _nonnegative_number(config["critical"], f"{name}.critical")
    config["sustained_samples"] = _positive_integer(
        config["sustained_samples"], f"{name}.sustained_samples"
    )
    if config["direction"] == "above" and config["critical"] < config["warning"]:
        raise ConfigError(f"{name}.critical must be greater than or equal to warning")
    if config["direction"] == "below" and config["critical"] > config["warning"]:
        raise ConfigError(f"{name}.critical must be less than or equal to warning")
    return config


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
    history = _require_mapping(config.get("history"), "history")
    history.setdefault("enabled", True)
    history.setdefault("retention_days", 30)
    history.setdefault("max_observations_per_resource", 1440)
    history.setdefault("max_total_observations", 50000)
    history.setdefault("recent_event_limit", 20)
    history.setdefault("trend_point_limit", 30)
    history.setdefault("queue_size", 512)
    history["enabled"] = _boolean(history["enabled"], "history.enabled")
    history["path"] = _state_path(history.get("path"), config_path)
    for setting in (
        "retention_days",
        "max_observations_per_resource",
        "max_total_observations",
        "recent_event_limit",
        "trend_point_limit",
        "queue_size",
    ):
        history[setting] = _positive_integer(history[setting], f"history.{setting}")
    config["history"] = history

    notifications = _require_mapping(config.get("notifications"), "notifications")
    notifications.setdefault("enabled", False)
    notifications.setdefault("minimum_severity", "warning")
    notifications.setdefault("degraded_grace_seconds", 60)
    notifications.setdefault("unavailable_grace_seconds", 90)
    notifications.setdefault("cooldown_seconds", 900)
    notifications.setdefault("recovery_messages", True)
    notifications.setdefault("queue_size", 64)
    notifications.setdefault("retry_limit", 3)
    notifications["enabled"] = _boolean(notifications["enabled"], "notifications.enabled")
    notifications["recovery_messages"] = _boolean(
        notifications["recovery_messages"], "notifications.recovery_messages"
    )
    if notifications["minimum_severity"] not in {"info", "warning", "critical"}:
        raise ConfigError("notifications.minimum_severity must be 'info', 'warning', or 'critical'")
    for setting in ("degraded_grace_seconds", "unavailable_grace_seconds", "cooldown_seconds"):
        notifications[setting] = _nonnegative_number(
            notifications[setting], f"notifications.{setting}"
        )
    for setting in ("queue_size", "retry_limit"):
        notifications[setting] = _positive_integer(
            notifications[setting], f"notifications.{setting}"
        )
    quiet_hours = _require_mapping(notifications.get("quiet_hours"), "notifications.quiet_hours")
    quiet_hours.setdefault("enabled", False)
    quiet_hours.setdefault("start", "22:00")
    quiet_hours.setdefault("end", "07:00")
    quiet_hours.setdefault("timezone", "local")
    quiet_hours["enabled"] = _boolean(quiet_hours["enabled"], "notifications.quiet_hours.enabled")
    quiet_hours["start"] = _clock_time(quiet_hours["start"], "notifications.quiet_hours.start")
    quiet_hours["end"] = _clock_time(quiet_hours["end"], "notifications.quiet_hours.end")
    timezone = str(quiet_hours["timezone"])
    if timezone != "local":
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError("notifications.quiet_hours.timezone is not recognized") from exc
    quiet_hours["timezone"] = timezone
    notifications["quiet_hours"] = quiet_hours
    config["notifications"] = notifications

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
        host["certificate_thresholds"] = _thresholds(
            host.get("certificate_thresholds"),
            f"hosts[{index}].certificate_thresholds",
            direction="below",
            default_warning=30,
            default_critical=7,
        )
        metrics = _require_mapping(host.get("metrics"), f"hosts[{index}].metrics")
        metrics.setdefault("enabled", bool(metrics))
        metrics["enabled"] = _boolean(metrics["enabled"], f"hosts[{index}].metrics.enabled")
        if metrics["enabled"]:
            url = str(metrics.get("url") or "")
            if not url.startswith("https://"):
                raise ConfigError(f"hosts[{index}].metrics.url must use https://")
            metrics["url"] = url
            metrics["poll_interval_seconds"] = _positive_number(
                metrics.get("poll_interval_seconds", host["poll_interval_seconds"]),
                f"hosts[{index}].metrics.poll_interval_seconds",
            )
            metrics["timeout_seconds"] = _positive_number(
                metrics.get("timeout_seconds", host["timeout_seconds"]),
                f"hosts[{index}].metrics.timeout_seconds",
            )
            _normalize_tls(metrics, f"hosts[{index}].metrics", config_path.resolve().parent)
            api_key_env = metrics.get("api_key_env")
            if api_key_env:
                token = os.getenv(str(api_key_env))
                if not token:
                    raise ConfigError(
                        f"Environment variable {api_key_env} is required by hosts[{index}].metrics"
                    )
                metrics["api_key"] = token
            if "api_key" in metrics and not api_key_env:
                raise ConfigError(
                    f"hosts[{index}].metrics.api_key must use an api_key_env reference"
                )
            threshold_defaults = {
                "disk_used_percent": ("above", 80, 90, 1),
                "temperature_c": ("above", 70, 85, 1),
                "backup_age_hours": ("above", 24, 48, 1),
                "cpu_used_percent": ("above", 85, 95, 3),
                "memory_used_percent": ("above", 85, 95, 3),
            }
            raw_thresholds = _require_mapping(
                metrics.get("thresholds"), f"hosts[{index}].metrics.thresholds"
            )
            metrics["thresholds"] = {
                key: _thresholds(
                    raw_thresholds.get(key),
                    f"hosts[{index}].metrics.thresholds.{key}",
                    direction=defaults[0],
                    default_warning=defaults[1],
                    default_critical=defaults[2],
                    default_sustained_samples=defaults[3],
                )
                for key, defaults in threshold_defaults.items()
            }
        host["metrics"] = metrics

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
        if provider_name == "portainer":
            provider["max_inspections_per_poll"] = _positive_integer(
                provider.get("max_inspections_per_poll", 20),
                "portainer.max_inspections_per_poll",
            )
            provider["inspect_baseline_interval_seconds"] = _positive_number(
                provider.get("inspect_baseline_interval_seconds", 300),
                "portainer.inspect_baseline_interval_seconds",
            )
            provider["restart_warning_count"] = _positive_integer(
                provider.get("restart_warning_count", 3),
                "portainer.restart_warning_count",
            )
            provider["restart_critical_count"] = _positive_integer(
                provider.get("restart_critical_count", 10),
                "portainer.restart_critical_count",
            )
            if provider["restart_critical_count"] < provider["restart_warning_count"]:
                raise ConfigError(
                    "portainer.restart_critical_count must be greater than or equal to warning"
                )
            provider["recent_exit_window_seconds"] = _positive_number(
                provider.get("recent_exit_window_seconds", 3600),
                "portainer.recent_exit_window_seconds",
            )
            endpoint_host_map = _require_mapping(
                provider.get("endpoint_host_map"), "portainer.endpoint_host_map"
            )
            provider["endpoint_host_map"] = {
                str(endpoint_id): str(host_id) for endpoint_id, host_id in endpoint_host_map.items()
            }
        if provider_name == "jellyfin" and provider.get("host_id") is not None:
            provider["host_id"] = str(provider["host_id"])
        config[provider_name] = provider
    dependencies = {
        *config["portainer"].get("endpoint_host_map", {}).values(),
        *([config["jellyfin"]["host_id"]] if config["jellyfin"].get("host_id") is not None else []),
    }
    unknown_dependencies = dependencies - host_ids
    if unknown_dependencies:
        raise ConfigError(
            "dependency mappings reference unknown host ids: "
            + ", ".join(sorted(unknown_dependencies))
        )

    return config
