"""Flask application factory."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from flask import Flask, jsonify

from homelab_monitor.config import load_config
from homelab_monitor.models import API_VERSION, COLLECTOR_VERSION
from homelab_monitor.service import DashboardService


def create_app(
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
) -> Flask:
    app = Flask(__name__)
    collector_config = config if config is not None else load_config(config_path)
    service = DashboardService(collector_config)
    service.start()
    app.extensions["homelab_monitor_service"] = service

    @app.get("/healthz")
    def health() -> Any:
        return jsonify(
            {
                "status": "ok",
                "api_version": API_VERSION,
                "collector_version": COLLECTOR_VERSION,
            }
        )

    @app.get("/api/v1/dashboard")
    def dashboard_v1() -> Any:
        return jsonify(service.snapshot().to_v1_dict())

    @app.get("/api/v2/dashboard")
    def dashboard_v2() -> Any:
        return jsonify(service.snapshot().to_dict())

    @app.get("/api/v2/schema")
    def dashboard_schema() -> Any:
        schema_path = files("homelab_monitor.schema").joinpath("dashboard-v2.schema.json")
        return jsonify(json.loads(schema_path.read_text(encoding="utf-8")))

    return app
