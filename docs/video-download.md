# Video download (standalone)

Separate web app from the mini-PC dashboard. Paste a YouPorn URL and save the file to RAID storage via `yt-dlp`.

## URL

**http://192.168.1.30:8083/** (port and `public_url` in `config/settings.yaml` → `video_download`)

## One-time install (mini-PC)

```bash
cd ~/mini-pc-monitor
pip install -r requirements.txt   # or: .venv + requirements.txt
bash scripts/install-video-download-service.sh
```

The dashboard on port **8080** does not link to this tool — bookmark the URL above.

## Config

See `video_download` in `config/settings.yaml` (`download_dir`, `allowed_hosts`, `port`).
