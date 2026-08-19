"""External provider adapters."""

from homelab_monitor.providers.hosts import probe_host
from homelab_monitor.providers.jellyfin import JellyfinClient
from homelab_monitor.providers.portainer import PortainerClient

__all__ = ["JellyfinClient", "PortainerClient", "probe_host"]
