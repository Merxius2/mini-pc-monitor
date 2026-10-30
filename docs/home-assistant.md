# Home Assistant + RFLink (433 MHz)

Runs on the mini PC at **http://192.168.1.30:8123/** via Docker.

## Hardware

| Piece | Notes |
|-------|--------|
| Arduino Mega + RFLink firmware | Same setup as former Domoticz on Synology |
| USB serial (CH340) | Stable path: `/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0` → `ttyUSB0` |
| 433 MHz transmitter | RFLink gateway at **57600 baud** |

Domoticz and Home Assistant both speak to **RFLink** — no Domoticz required on the NAS.

## Install / update

```bash
cd ~/mini-pc-monitor
bash scripts/install-homeassistant.sh
sudo systemctl status homeassistant
docker logs -f homeassistant
```

If the UI works on the mini PC but not from another device on LAN, allow **8123/tcp** in UFW (the install script does this when UFW is active):

```bash
sudo ufw allow 8123/tcp comment 'Home Assistant'
```

## KlikAanKlikUit sockets (433 MHz)

Do **not** add the **KlikAanKlikUit** integration from the UI. That flow expects a separate “Radio Frequency transmitter” entity (e.g. ESPHome OOK TX). Your transmitter is the **Arduino Mega + RFLink** USB gateway, already configured under **`rflink:`** in `configuration.yaml`.

Use RFLink the same way you did in Domoticz: learn codes from the remote, then control via `newkaku_…` device ids.

## GUI: see detected RF signals (Domoticz-style)

The **built-in RFLink integration** (YAML) has **no** Domoticz-like “RF sniffer” page. What you get in the UI:

| Where | What you see |
|--------|----------------|
| **Settings → Entities** | Filter `light.` / `rflink` — devices appear after `automatic_add` picks up a button press (often as **lights**, not switches). |
| **Developer tools → Events** | Subscribe to event type `rflink_event` (or watch **Logs** with filter `rflink`) while pressing remotes — raw protocol lines, closest to Domoticz logs. |
| **Settings → Devices & services → RFLink** | Hub only; not a full device browser. |

For a **Domoticz-like flow** (“recently detected signals → add as switch/light”), use the community **[RFLink UI](https://github.com/guanaco0403/Home-Assistant-Rflink-UI)** integration via **HACS**:

1. Install [HACS](https://hacs.xyz/docs/setup/download) in Home Assistant (one-time).
2. HACS → Custom repositories → add `https://github.com/guanaco0403/Home-Assistant-Rflink-UI` (category **Integration**).
3. Install **RFLink UI**, restart HA.
4. **Remove or comment out** the `rflink:` block in `configuration.yaml` (only one integration may use the serial port).
5. **Settings → Add integration → RFLink UI** → port `/dev/rflink` (inside the container).
6. On the integration card → **Configure → Add recently detected device** (press remotes first).

That options screen is the nearest equivalent to Domoticz’s detected-device list.

## Pair power sockets

1. **Settings → Devices & services** — confirm **RFLink** is loaded (YAML). Ignore **KlikAanKlikUit** in “Add integration”.
2. Open **Developer Tools → States** and filter `light.` or `rflink`.
3. Press **on** on the physical remote for a socket.
4. A new entity appears (often `light.newkaku_<hex>_<channel>`) because `automatic_add` is enabled for lights.
5. Add a proper **switch** in `~/homeassistant/config/configuration.yaml`:

```yaml
switch:
  - platform: rflink
    devices:
      newkaku_0a1b2c_01:
        name: Desk socket
        signal_repetitions: 3
```

Use the exact device id from the discovered entity (without the `light.` prefix). Restart Home Assistant after editing.

## Useful commands

```bash
sudo systemctl restart homeassistant
docker logs homeassistant 2>&1 | grep -i rflink
```

If the USB path changes after reboot, update `RFLINK_DEVICE` in `/etc/systemd/system/homeassistant.service` and re-run the install script.
