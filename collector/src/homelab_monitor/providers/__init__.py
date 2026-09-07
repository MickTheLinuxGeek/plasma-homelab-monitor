"""External provider adapters."""

from homelab_monitor.providers.host_metrics import HostMetricsClient, normalize_host_metrics
from homelab_monitor.providers.hosts import probe_host, verified_certificate_expiry
from homelab_monitor.providers.jellyfin import JellyfinClient
from homelab_monitor.providers.portainer import InspectCacheEntry, PortainerClient

__all__ = [
    "HostMetricsClient",
    "InspectCacheEntry",
    "JellyfinClient",
    "PortainerClient",
    "normalize_host_metrics",
    "probe_host",
    "verified_certificate_expiry",
]
