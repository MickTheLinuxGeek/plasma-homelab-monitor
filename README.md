# Home-lab Monitor

A Plasma 6 panel widget backed by a small local Flask collector. It provides a compact, read-only view of:

- NAS and host reachability through HTTP or TCP probes
- Docker environments and containers through Portainer
- Jellyfin server status and active playback sessions

The widget never stores infrastructure credentials. Portainer and Jellyfin tokens remain in the collector's environment, and the widget receives only normalized status data.

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
curl http://127.0.0.1:8765/api/v2/dashboard
make preview
```

The widget defaults to `http://127.0.0.1:8765` and refreshes every 30 seconds. Both values can be changed from the widget's settings. Provider probes run independently in the collector; dashboard HTTP requests return the latest cached snapshot immediately.

The current contract is available at `/api/v2/dashboard`, with its JSON Schema at `/api/v2/schema`. `/api/v1/dashboard` remains available for v0.2 widget compatibility.

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

These probes report availability and latency. They intentionally do not claim to provide CPU, disk, temperature, or SMART metrics; those require a future metrics adapter.

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
```

An empty `endpoint_ids` list includes all environments visible to the token. The adapter only performs `GET` requests.

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
```

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

The supplied service assumes the project remains at `~/Dev_Projects/homelab-plasma-monitor`.

## Development checks

```bash
make format
make check
```

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
