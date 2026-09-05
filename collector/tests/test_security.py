from __future__ import annotations

import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
import trustme
from homelab_monitor.cli import is_loopback_host
from homelab_monitor.config import ConfigError, load_config
from homelab_monitor.models import Status
from homelab_monitor.providers.hosts import probe_host


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


def test_local_ca_https_probe_verifies_successfully(tmp_path: Path) -> None:
    ca = trustme.CA()
    certificate = ca.issue_cert("localhost")
    ca_path = tmp_path / "home-lab-ca.pem"
    ca.cert_pem.write_to_path(ca_path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(context)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = probe_host(
            {
                "id": "secure-host",
                "name": "Secure host",
                "probe": {
                    "type": "http",
                    "url": f"https://localhost:{server.server_port}/health",
                    "verify_tls": True,
                    "ca_bundle": str(ca_path),
                },
            },
            timeout=1,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert result.status == Status.HEALTHY
    assert result.certificate_expires_at is not None
    assert result.certificate_days_remaining is not None
    assert result.certificate_days_remaining > 0


def test_config_resolves_relative_ca_bundle(tmp_path: Path) -> None:
    ca = trustme.CA()
    ca.cert_pem.write_to_path(tmp_path / "ca.pem")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "demo: true\n"
        "hosts:\n"
        "  - id: host\n"
        "    probe:\n"
        "      type: http\n"
        "      url: https://host.example.test\n"
        "      ca_bundle: ca.pem\n"
        "portainer:\n"
        "  enabled: false\n"
        "jellyfin:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["hosts"][0]["probe"]["ca_bundle"] == str((tmp_path / "ca.pem").resolve())
    assert config["hosts"][0]["probe"]["verify_tls"] is True


def test_disabling_tls_requires_explicit_insecure_opt_in(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "demo: true\n"
        "hosts:\n"
        "  - id: host\n"
        "    probe:\n"
        "      type: http\n"
        "      url: https://host.example.test\n"
        "      verify_tls: false\n"
        "portainer:\n"
        "  enabled: false\n"
        "jellyfin:\n"
        "  enabled: false\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="allow_insecure_tls"):
        load_config(config_path)


def test_environment_file_must_be_private(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PORTAINER_API_KEY=not-exposed\n", encoding="utf-8")
    (tmp_path / ".env").chmod(0o644)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("demo: true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="group or other users"):
        load_config(config_path)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_bind_addresses_are_allowed(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "collector.example.test"])
def test_unauthenticated_remote_bind_addresses_are_rejected(host: str) -> None:
    assert not is_loopback_host(host)
