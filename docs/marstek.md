# Marstek Venus (local API)

Dashboard page: **http://192.168.1.30:8080/batteries**

## Setup on the battery

1. In the Marstek app, enable **Local API** for each Venus V3.
2. Devices listen for JSON-RPC over **UDP port 30000**.
3. The dashboard also **binds local UDP port 30000** when talking to devices (required for replies).

## Discovery

- **Scan LAN** broadcasts `Marstek.GetDevice` to the hosts in `marstek.broadcast_hosts` (`config/settings.yaml`).
- **Add by IP** queries a single host if broadcast is blocked on your network.

## Polling (Wi‑Fi)

Marstek devices on Wi‑Fi rate-limit back-to-back UDP queries (~3.7 s). The dashboard spaces requests (`request_delay: 3.8`) and only accepts replies from the target IP (needed when several batteries share port 30000). A background poller refreshes selected units so page loads stay fast.

On some Venus E firmware (e.g. 148), `ES.GetStatus` may time out; power and SOC are taken from `ES.GetMode`, `EM.GetStatus`, and `Bat.GetStatus` instead.

Device IPs reported as `192.168.01.27` are normalised to `192.168.1.27`.

Selected devices are stored in `/var/lib/mini-pc-monitor/marstek.json`.

## CT clamp notifications

When a monitored device reports `ct_state: 0` (CT link lost) for longer than `ct_alert_after_seconds` (default **5 minutes**), the page shows a banner and triggers a browser notification (enable notifications when prompted; on iPhone, open the dashboard from the home screen).

## Config

```yaml
marstek:
  enabled: true
  broadcast_hosts:
    - 192.168.1.255
  manual_hosts: []   # optional fixed IPs to always probe on scan
  ct_alert_after_seconds: 300
```
