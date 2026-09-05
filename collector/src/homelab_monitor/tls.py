"""TLS verification helpers shared by HTTP providers."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any


def tls_verification(config: dict[str, Any]) -> bool | ssl.SSLContext:
    """Build an HTTPX verify value, including a configured private CA bundle."""
    if not bool(config.get("verify_tls", True)):
        return False
    ca_bundle = config.get("ca_bundle")
    if not ca_bundle:
        return True
    return ssl.create_default_context(cafile=str(Path(ca_bundle)))
