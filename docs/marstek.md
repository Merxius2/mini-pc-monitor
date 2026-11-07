# Marstek Venus (local API)

Dashboard page: **http://192.168.1.30:8080/batteries**

## Setup on the battery

1. In the Marstek app, enable **Local API** for each Venus V3.
2. Devices listen for JSON-RPC over **UDP port 30000**.
3. The dashboard also **binds local UDP port 30000** when talking to devices (required for replies).

## Discovery

- **Scan LAN** broadcasts `Marstek.GetDevice` to the hosts in `marstek.broadcast_hosts` (`config/settings.yaml`).
- **Add by IP** queries a single host if broadcast is blocked on your network.

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
