# Mini-PC Monitor

Web dashboard for the home mini-PC: CPU/memory gauges, sparklines, systemd service status, and restart actions.

Repurposed from the [news-trader-advisor](https://github.com/Merxius2/news-trader-advisor) Phase 2 dashboard UI — trader/news/Ollama automation removed.

## Mini-PC URL

`http://192.168.1.30:8080/` (LAN)

## One-time setup (on mini-PC)

```bash
git clone https://github.com/Merxius2/mini-pc-monitor.git ~/mini-pc-monitor
cd ~/mini-pc-monitor
bash scripts/install-dashboard-service.sh
bash scripts/install-deploy-trigger.sh
```

Auto-deploy polls `origin/main` every **3 minutes** and restarts the dashboard when new commits land.

## Config

Edit `config/settings.yaml`:

- `services` — systemd units to show (set `manage: true` to allow start/stop/restart from the UI)
- `server.port` — default `8080`

Service actions use `sudo -n systemctl start|stop|restart` (passwordless sudo required).

### AzerothCore WoW server

Install the bundled systemd units on the mini-PC (adjust paths in the unit files if needed):

```bash
bash scripts/install-azerothcore-service.sh
```

Grant the dashboard user passwordless control:

```sudoers
sylvester ALL=(ALL) NOPASSWD: /bin/systemctl start azerothcore*, /bin/systemctl stop azerothcore*, /bin/systemctl restart azerothcore*
```

## Local dev

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn src.web.app:app --reload --port 8080
```

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -q
```
