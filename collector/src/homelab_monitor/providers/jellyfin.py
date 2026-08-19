"""Read-only Jellyfin API adapter."""

from __future__ import annotations

from typing import Any

import httpx

from homelab_monitor.models import JellyfinSession, JellyfinStatus, Status


class JellyfinClient:
    def __init__(
        self,
        config: dict[str, Any],
        timeout: float,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.base_url = str(config["url"]).rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            verify=bool(config.get("verify_tls", True)),
            headers={"X-Emby-Token": str(config["api_key"])},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, path: str) -> Any:
        response = self.client.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    def collect(self) -> JellyfinStatus:
        try:
            system = self._get("/System/Info")
            raw_sessions = self._get("/Sessions")
            sessions = []
            for session in raw_sessions:
                now_playing = session.get("NowPlayingItem")
                if not now_playing:
                    continue
                sessions.append(
                    JellyfinSession(
                        user_name=str(session.get("UserName") or "Unknown user"),
                        client=str(session.get("Client") or "Unknown client"),
                        device_name=str(session.get("DeviceName") or "Unknown device"),
                        item_name=str(now_playing.get("Name") or "Unknown item"),
                    )
                )
            return JellyfinStatus(
                status=Status.HEALTHY,
                server_name=str(system.get("ServerName") or "Jellyfin"),
                version=str(system.get("Version") or ""),
                active_sessions=sessions,
                dashboard_url=self.base_url,
            )
        except (TypeError, ValueError, httpx.HTTPError) as exc:
            return JellyfinStatus(
                status=Status.UNAVAILABLE,
                dashboard_url=self.base_url,
                error=str(exc),
            )
        finally:
            self.close()
