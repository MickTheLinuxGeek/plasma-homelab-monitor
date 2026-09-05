"""Collector command-line interface."""

from __future__ import annotations

import argparse
from ipaddress import ip_address

from waitress import serve

from homelab_monitor.app import create_app


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description="Run the Home-lab Monitor collector")
    argument_parser.add_argument("--config", default=None, help="Path to YAML configuration")
    argument_parser.add_argument("--host", default="127.0.0.1", help="Listen address")
    argument_parser.add_argument("--port", default=8765, type=int, help="Listen port")
    argument_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    return argument_parser


def main() -> None:
    args = parser().parse_args()
    if not is_loopback_host(args.host):
        raise SystemExit(
            "Remote collector binding is disabled until authenticated HTTPS or mTLS is configured."
        )
    app = create_app(config_path=args.config)
    service = app.extensions["homelab_monitor_service"]
    try:
        if args.debug:
            app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
        else:
            serve(app, host=args.host, port=args.port)
    finally:
        service.stop()


if __name__ == "__main__":
    main()
