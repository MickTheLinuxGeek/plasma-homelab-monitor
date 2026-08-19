from typing import Any

import pytest


@pytest.fixture
def demo_config() -> dict[str, Any]:
    return {
        "demo": True,
        "request_timeout_seconds": 1.0,
        "hosts": [],
        "portainer": {"enabled": False, "verify_tls": True},
        "jellyfin": {"enabled": False, "verify_tls": True},
    }
