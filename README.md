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
curl http://127.0.0.1:8765/api/v1/dashboard
make preview
```

The widget defaults to `http://127.0.0.1:8765` and refreshes every 30 seconds. Both values can be changed from the widget's settings.

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

## Known follow-up: local certificate trust

Fedora command-line tools may trust home-lab certificates installed in the system CA store while Python HTTPX rejects the same certificates. HTTPX uses the bundled `certifi` CA store by default, which does not automatically include a private or locally generated certificate authority.

The Forgejo probe currently works around this by setting `verify_tls: false` in the local `config.yaml`. A future improvement should allow a custom CA bundle path—either as a supported `verify_tls` value or through a separate `ca_bundle` setting—so HTTPX can verify home-lab certificates without disabling TLS verification.

When implementing this, configure HTTPX with the PEM file for the home-lab CA rather than an individual server certificate, then return the Forgejo probe to verified TLS.

The collector binds to `127.0.0.1` by default. If it is later moved to a home-lab server, place it behind authenticated HTTPS or restrict access at the network layer before changing the listen address.
