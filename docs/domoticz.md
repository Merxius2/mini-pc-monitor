# Domoticz + RFLink

Runs on the mini PC at **http://192.168.1.30:8082/** (port **8082** — 8080 is the mini-PC monitor).

## Install

```bash
cd ~/mini-pc-monitor
bash scripts/install-domoticz.sh
sudo systemctl start domoticz.service
```

## RFLink hardware

After first login, add hardware: **Setup → Hardware → RFLink USB** → serial **`/dev/ttyUSB0`** (inside the container).

## Home Assistant vs Domoticz

Both use the same USB RFLink stick. systemd units **Conflict** — starting one stops the other. Use the **Services** page toggles on the mini-PC monitor to switch.

| Run | RFLink USB | Best for |
|-----|------------|----------|
| **Domoticz** | Yes | Domoticz-style RF sniffer / device list |
| **Home Assistant** | Yes (when Domoticz stopped) | HA automations + RFLink YAML / RFLink UI |

```sudoers
sylvester ALL=(ALL) NOPASSWD: /bin/systemctl start domoticz.service, /bin/systemctl stop domoticz.service, /bin/systemctl restart domoticz.service
```

UFW: `8123` (HA), `8082` (Domoticz).
