"""Online video downloads via yt-dlp (YouPorn and other configured hosts)."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.config_loader import VideoDownloadConfig

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, "DownloadJob"] = {}


@dataclass
class DownloadJob:
    id: str
    url: str
    status: str  # queued | running | done | error
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _yt_dlp_cmd(config: VideoDownloadConfig) -> list[str]:
    if config.yt_dlp_command:
        return config.yt_dlp_command.split()
    return [sys.executable, "-m", "yt_dlp"]


def _host_allowed(url: str, allowed_hosts: list[str]) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    allowed = {h.lower().lstrip(".") for h in allowed_hosts}
    for pattern in allowed:
        if host == pattern or host.endswith("." + pattern):
            return True
    return False


def validate_video_url(url: str, config: VideoDownloadConfig) -> tuple[bool, str]:
    raw = (url or "").strip()
    if not raw:
        return False, "Paste a video page URL"
    if not _host_allowed(raw, config.allowed_hosts):
        hosts = ", ".join(config.allowed_hosts)
        return False, f"URL must be from an allowed site ({hosts})"
    return True, ""


def yt_dlp_available(config: VideoDownloadConfig) -> tuple[bool, str | None]:
    cmd = _yt_dlp_cmd(config) + ["--version"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "yt-dlp not available").strip()
        return False, err.splitlines()[0] if err else "yt-dlp not available"
    version = (result.stdout or "").strip().splitlines()[0]
    return True, version or None


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} PB"


def list_recent_downloads(config: VideoDownloadConfig) -> list[dict[str, str]]:
    root = Path(config.download_dir)
    if not root.is_dir():
        return []
    files: list[tuple[float, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".part", ".ytdl", ".temp"}:
            continue
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(key=lambda item: item[0], reverse=True)
    out: list[dict[str, str]] = []
    for mtime, path in files[: config.max_recent_files]:
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root)
        out.append(
            {
                "name": str(rel),
                "size": _human_size(stat.st_size),
                "modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return out


def list_jobs() -> list[DownloadJob]:
    with _JOB_LOCK:
        jobs = list(_JOBS.values())
    jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)
    return jobs[:20]


def _set_job(job_id: str, **kwargs: object) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)


def _run_download(job_id: str, url: str, config: VideoDownloadConfig) -> None:
    _set_job(job_id, status="running", started_at=datetime.now())
    out_dir = Path(config.download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(out_dir / "%(title).180B [%(id)s].%(ext)s")
    cmd = _yt_dlp_cmd(config) + [
        "--no-playlist",
        "--restrict-filenames",
        "-o",
        output_template,
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.download_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        _set_job(
            job_id,
            status="error",
            message=f"Timed out after {config.download_timeout_seconds}s",
            finished_at=datetime.now(),
        )
        return
    except OSError as exc:
        _set_job(job_id, status="error", message=str(exc), finished_at=datetime.now())
        return

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "Download failed").strip()
        err = re.sub(r"\s+", " ", err)
        if len(err) > 400:
            err = err[:397] + "..."
        _set_job(job_id, status="error", message=err, finished_at=datetime.now())
        return

    _set_job(job_id, status="done", message="Saved to download folder", finished_at=datetime.now())


def start_download(url: str, config: VideoDownloadConfig) -> tuple[bool, str, str | None]:
    ok, message = validate_video_url(url, config)
    if not ok:
        return False, message, None
    available, ver_err = yt_dlp_available(config)
    if not available:
        return False, ver_err or "yt-dlp is not installed", None

    job_id = uuid.uuid4().hex[:12]
    job = DownloadJob(id=job_id, url=url.strip(), status="queued")
    with _JOB_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > 50:
            oldest = sorted(_JOBS.values(), key=lambda j: j.started_at or datetime.min)
            for stale in oldest[: len(_JOBS) - 50]:
                _JOBS.pop(stale.id, None)

    thread = threading.Thread(
        target=_run_download,
        args=(job_id, url.strip(), config),
        name=f"video-download-{job_id}",
        daemon=True,
    )
    thread.start()
    return True, "Download started — refresh below for progress", job_id


def get_video_download_status(config: VideoDownloadConfig) -> dict:
    available, version_or_err = yt_dlp_available(config)
    mount = Path(config.download_dir)
    dir_ok = mount.is_dir() or mount.parent.is_dir()
    active = sum(1 for j in list_jobs() if j.status in ("queued", "running"))
    return {
        "enabled": config.enabled,
        "yt_dlp_ok": available,
        "yt_dlp_version": version_or_err if available else None,
        "yt_dlp_error": None if available else version_or_err,
        "download_dir": config.download_dir,
        "download_dir_ready": dir_ok,
        "allowed_hosts": config.allowed_hosts,
        "active_jobs": active,
        "jobs": list_jobs(),
        "recent_files": list_recent_downloads(config),
    }
