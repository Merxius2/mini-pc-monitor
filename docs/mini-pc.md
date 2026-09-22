# Mini-PC deployment

Runtime target: **192.168.1.30** · user `sylvester` · repo path `~/mini-pc-monitor`

## Services

| systemd unit | Purpose |
|--------------|---------|
| `mini-pc-monitor.service` | FastAPI dashboard on `0.0.0.0:8080` |
| `mini-pc-monitor-deploy.timer` | Poll GitHub every 3 min → pull + restart if `main` changed |

## Commands

```bash
sudo systemctl status mini-pc-monitor
sudo systemctl restart mini-pc-monitor
journalctl -u mini-pc-monitor-deploy.service -n 20
systemctl list-timers mini-pc-monitor-deploy.timer
```

## Manual update

```bash
cd ~/mini-pc-monitor && bash scripts/pull-on-mini-pc.sh
```

## Legacy

The news-trader-advisor dashboard and its deploy timer should stay **disabled** on this machine. Trading development continues in the other repo without a live dashboard here.
