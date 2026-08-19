"""Flask application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify

from homelab_monitor.config import load_config
from homelab_monitor.service import DashboardService


def create_app(
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> Flask:
    app = Flask(__name__)
    collector_config = config if config is not None else load_config(config_path)
    service = DashboardService(collector_config)

    @app.get("/healthz")
    def health() -> Any:
        return jsonify({"status": "ok"})

    @app.get("/api/v1/dashboard")
    def dashboard() -> Any:
        return jsonify(service.collect().to_dict())

    return app
