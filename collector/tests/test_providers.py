import httpx
from homelab_monitor.models import Status
from homelab_monitor.providers.hosts import probe_host
from homelab_monitor.providers.jellyfin import JellyfinClient
from homelab_monitor.providers.portainer import PortainerClient


def test_invalid_host_probe_is_reported_as_unavailable() -> None:
    result = probe_host(
        {"id": "nas", "name": "NAS", "probe": {"type": "unsupported"}},
        timeout=0.1,
    )

    assert result.status == Status.UNAVAILABLE
    assert "probe.type" in result.detail


def test_portainer_normalizes_environments_and_containers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/endpoints":
            return httpx.Response(200, json=[{"Id": 1, "Name": "NAS", "Status": 1}])
        if request.url.path.endswith("/containers/json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": "abc",
                        "Names": ["/gitea"],
                        "Image": "gitea/gitea:latest",
                        "State": "running",
                        "Status": "Up 2 days",
                    },
                    {
                        "Id": "def",
                        "Names": ["/wiki"],
                        "Image": "requarks/wiki:latest",
                        "State": "exited",
                        "Status": "Exited (1)",
                    },
                ],
            )
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    result = PortainerClient(
        {
            "url": "https://portainer.example.test",
            "api_key": "test",
            "verify_tls": True,
            "endpoint_ids": [],
        },
        timeout=1,
        client=http_client,
    ).collect()

    assert result.status == Status.DEGRADED
    assert result.environments[0].running == 1
    assert result.environments[0].stopped == 1
    assert result.environments[0].containers[0].name == "gitea"


def test_jellyfin_only_returns_active_playback_sessions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/System/Info":
            return httpx.Response(200, json={"ServerName": "Media", "Version": "10.10"})
        if request.url.path == "/Sessions":
            return httpx.Response(
                200,
                json=[
                    {
                        "UserName": "Mick",
                        "Client": "Web",
                        "DeviceName": "Laptop",
                        "NowPlayingItem": {"Name": "A Movie"},
                    },
                    {"UserName": "Idle User", "Client": "TV"},
                ],
            )
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    result = JellyfinClient(
        {
            "url": "https://jellyfin.example.test",
            "api_key": "test",
            "verify_tls": True,
        },
        timeout=1,
        client=http_client,
    ).collect()

    assert result.status == Status.HEALTHY
    assert result.server_name == "Media"
    assert len(result.active_sessions) == 1
    assert result.active_sessions[0].item_name == "A Movie"
