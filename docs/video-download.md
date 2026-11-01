# Video download

Integrated into the mini-PC dashboard. Paste a YouTube or other allow-listed video URL and save as MP4 or MP3 (MP3 needs `ffmpeg`) via `yt-dlp`.

## URL

**http://192.168.1.30:8080/video-download** (same app as the dashboard on port **8080**)

Also linked in the sidebar when `video_download.enabled` is true.

## Config

See `video_download` in `config/settings.yaml` (`video_dir`, `music_dir`, `allowed_hosts`).

Default layout on RAID:

- `…/Downloads/youtube downloader/videos` — MP4
- `…/Downloads/youtube downloader/music` — MP3

## Legacy standalone service (:8083)

If you previously ran `video-download.service`, disable it:

```bash
bash scripts/install-video-download-service.sh
```
