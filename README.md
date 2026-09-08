# Home-lab Monitor

A Plasma 6 panel widget backed by a small local Flask collector. It provides a compact, read-only view of:

- NAS and host reachability through HTTP or TCP probes
- Optional host metrics, certificate expiry, and reboot signals
- Docker environments and containers through Portainer
- Jellyfin server status and active playback sessions
- A retained incident timeline, bounded trends, and opt-in Plasma notifications

The widget never stores infrastructure credentials. Portainer, Jellyfin, and host metrics tokens remain in the collector's environment, and the widget receives only normalized status data.

## Project layout

- `collector/src/homelab_monitor/` — Flask API, provider adapters, and dashboard models
- `collector/tests/` — unit, API-contract, and package tests
- `plasmoid/package/` — installable Plasma 6 widget
- `systemd/` — optional user service

## Quick start in demo mode

```bash
cd /home/mick/Dev_Projects/homelab-plasma-monitor
make setup
make config
make run
```


The example configuration starts in demo mode. In another terminal:

```bash
curl http://127.0.0.1:8765/api/v3/dashboard
make preview
```

The widget defaults to `http://127.0.0.1:8765` and refreshes every 30 seconds. Both values can be changed from the widget's settings. Provider probes run independently in the collector; dashboard HTTP requests return the latest cached snapshot immediately.

The current contract is available at `/api/v3/dashboard`, with its JSON Schema at `/api/v3/schema`. `/api/v1/dashboard` and `/api/v2/dashboard` remain available for older widget compatibility.

## Configure live integrations

Copy the templates:

```bash
cp config.example.yaml config.yaml
cp .env.example .env
chmod 600 .env
```

Set `demo: false` in `config.yaml`. Replace the example hostnames and addresses, then enable the providers you want.

### Host probes

HTTP probes consider any successful 2xx/3xx response healthy:

```yaml
hosts:
  - id: dxp2800
    name: DXP2800
    dashboard_url: https://omv.home.arpa
    probe:
      type: http
      url: https://omv.home.arpa
      verify_tls: true
```

TCP probes verify that a port accepts a connection:

```yaml
hosts:
  - id: dxp4800p
    name: DXP4800 Plus
    probe:
      type: tcp
      host: 192.168.1.20
      port: 22
```

Reachability remains independent from optional host metrics. A metrics endpoint failure can make metrics stale or unavailable without falsely reporting that the host itself is unreachable. Configure only verified HTTPS endpoints, and keep bearer tokens in `.env` through `api_key_env`.

Each HTTP probe also reports certificate expiry when the TLS peer exposes a certificate. The default warning and critical thresholds are 30 and 7 days.

### Host metrics endpoint

The optional endpoint must return a strict version 1 JSON object. Unknown fields are rejected; only `schema_version` and a timezone-aware `observed_at` timestamp are required. Omitted metric categories appear as unknown rather than healthy.

```json
{
  "schema_version": "1",
  "observed_at": "2026-09-05T18:00:00Z",
  "boot_id": "8a9f4c1e",
  "disks": [
    {"id": "data", "label": "Data array", "used_percent": 61.4}
  ],
  "temperatures": [
    {"id": "cpu", "label": "CPU package", "celsius": 42.0}
  ],
  "smart": [
    {"id": "nvme0", "label": "System NVMe", "status": "passed"}
  ],
  "backups": [
    {
      "id": "restic",
      "label": "Restic",
      "last_success_at": "2026-09-05T03:00:00Z"
    }
  ],
  "cpu": {"used_percent": 38.2},
  "memory": {"used_percent": 57.1}
}
```

Disk and percentage values must be finite numbers from 0 through 100. Temperatures accept finite Celsius values. SMART status is `passed`, `failed`, or `unknown`; backup timestamps must be timezone-aware and not in the future. `boot_id` is baseline-only on first observation and creates a reboot event only when a later value differs. CPU and memory incident transitions require their configured consecutive sample count.

### History and notifications

The collector stores bounded observations, events, and trends in SQLite by default. The database defaults to `~/.local/state/homelab-monitor/history.sqlite3`; retention and row caps are configurable under `history`.

Collector-owned Plasma notifications are disabled by default. To opt in:

```yaml
notifications:
  enabled: true
  minimum_severity: warning
  degraded_grace_seconds: 60
  unavailable_grace_seconds: 90
  cooldown_seconds: 900
  recovery_messages: true
  quiet_hours:
    enabled: true
    start: "22:00"
    end: "07:00"
    timezone: local
```

Notifications are sent over the logged-in Plasma session's D-Bus. Grace periods, cooldowns, quiet hours, and recovery messages are evaluated by the collector, so the widget does not need to remain open.

### Portainer

Create a dedicated Portainer user with access only to the environments the widget should monitor, then create an access token for that user. Put the token in `.env`:

```text
PORTAINER_API_KEY=replace-with-the-token
```

Enable the adapter in `config.yaml`:

```yaml
portainer:
  enabled: true
  url: https://portainer.home.arpa
  api_key_env: PORTAINER_API_KEY
  verify_tls: true
  endpoint_ids: []
  max_inspections_per_poll: 20
  inspect_baseline_interval_seconds: 300
  endpoint_host_map:
    "1": dxp2800
```

An empty `endpoint_ids` list includes all environments visible to the token. The adapter only performs `GET` requests. Container inspection is prioritized for unhealthy or restarting containers and bounded per poll; periodic baseline inspections catch restart, OOM, and recent-exit signals without inspecting the entire fleet on every refresh.

Set `endpoint_host_map` only for explicit, known dependencies. A mapped host failure can explain affected services in the timeline without turning correlation into an inferred dependency.

### Jellyfin

Create an API key in the Jellyfin administration dashboard and store it in `.env`:

```text
JELLYFIN_API_KEY=replace-with-the-key
```

Enable Jellyfin in `config.yaml`:

```yaml
jellyfin:
  enabled: true
  url: https://jellyfin.home.arpa
  api_key_env: JELLYFIN_API_KEY
  verify_tls: true
  host_id: jellyfin
```

`host_id` is optional and must reference a configured host. It records an explicit dependency for event correlation.

## Install the widget

```bash
make install-widget
```

Add **Home-lab Monitor** from Plasma's widget picker. For development, run:

```bash
make preview
```

Uninstall it with:

```bash
make uninstall-widget
```

## Run the collector as a user service

After `make setup`, `make config`, and live configuration:

```bash
make install-service
```

Inspect logs with:

```bash
journalctl --user -u homelab-monitor.service -f
```

The supplied service assumes the project remains at `~/Dev_Projects/homelab-plasma-monitor` and provisions `~/.local/state/homelab-monitor` with mode `0700` for the history database.

## Development checks

```bash
make format
make check
```

## Automated pull request reviews

GitHub Actions runs an Oz code review when a pull request is opened, marked
ready for review, or updated. Configure the repository's `WARP_API_KEY`
Actions secret to enable the workflow in `.github/workflows/oz-pr-review.yml`.

## Local certificate trust

Fedora command-line tools may trust home-lab certificates installed in the system CA store while Python HTTPX uses a different trust store. Configure `ca_bundle` for each HTTPS host probe or provider that uses a private CA:

```yaml
probe:
  type: http
  url: https://forgejo.home.arpa
  verify_tls: true
  ca_bundle: ~/.config/homelab-monitor/home-lab-ca.pem
```

Use the PEM certificate for the home-lab CA rather than an individual server certificate. Disabling verification requires both `verify_tls: false` and `allow_insecure_tls: true` as an explicit temporary exception.

The collector binds to `127.0.0.1` by default and rejects non-loopback bind addresses. Remote access will remain disabled until authenticated HTTPS or mutual TLS is implemented.

Keep `.env` mode `0600`; the collector refuses to start when the adjacent environment file is accessible to group or other users. Provider exception details are written only to collector logs. API responses contain sanitized error categories and messages.
