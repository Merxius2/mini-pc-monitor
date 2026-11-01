"""Online video downloads via yt-dlp for configured allowed hosts."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from src.config_loader import VideoDownloadConfig

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, "DownloadJob"] = {}

DownloadFormat = Literal["video", "audio"]


@dataclass
class DownloadJob:
    id: str
    url: str
    status: str  # queued | running | done | error
    format: DownloadFormat = "video"
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


def normalize_download_format(raw: str | None) -> DownloadFormat:
    value = (raw or "video").strip().lower()
    if value in ("audio", "mp3", "audio_only"):
        return "audio"
    return "video"


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


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


def output_dir_for_format(
    config: VideoDownloadConfig, download_format: DownloadFormat
) -> Path:
    if download_format == "audio":
        return Path(config.music_dir)
    return Path(config.video_dir)


def list_jobs() -> list[DownloadJob]:
    with _JOB_LOCK:
        jobs = list(_JOBS.values())
    jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)
    return jobs[:20]


def clear_jobs_display() -> tuple[bool, str]:
    """Remove finished jobs from the UI list; keeps queued/running jobs."""
    with _JOB_LOCK:
        active = [j for j in _JOBS.values() if j.status in ("queued", "running")]
        removed = 0
        for job_id, job in list(_JOBS.items()):
            if job.status in ("done", "error"):
                _JOBS.pop(job_id, None)
                removed += 1
        if active:
            if removed:
                return True, "Cleared finished jobs"
            return True, "No finished jobs to clear"
        _JOBS.clear()
        return True, "Jobs list cleared"


def reset_jobs_display() -> None:
    """Test helper: drop all jobs from memory."""
    with _JOB_LOCK:
        _JOBS.clear()


def _set_job(job_id: str, **kwargs: object) -> None:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for key, value in kwargs.items():
            setattr(job, key, value)


def build_yt_dlp_download_command(
    url: str,
    config: VideoDownloadConfig,
    download_format: DownloadFormat,
) -> list[str]:
    out_dir = output_dir_for_format(config, download_format)
    output_template = str(out_dir / "%(title).180B [%(id)s].%(ext)s")
    cmd = _yt_dlp_cmd(config) + [
        "--no-playlist",
        "--restrict-filenames",
        "-o",
        output_template,
    ]
    if download_format == "audio":
        cmd += ["-x", "--audio-format", "mp3", "--embed-thumbnail"]
    else:
        cmd += [
            "-f",
            (
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[ext=mp4]+bestaudio/"
                "best[ext=mp4]/"
                "bestvideo+bestaudio/best"
            ),
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
        ]
    cmd.append(url)
    return cmd


def _run_download(
    job_id: str,
    url: str,
    config: VideoDownloadConfig,
    download_format: DownloadFormat,
) -> None:
    _set_job(job_id, status="running", started_at=datetime.now())
    out_dir = output_dir_for_format(config, download_format)
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_yt_dlp_download_command(url, config, download_format)
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

    done_msg = (
        f"Saved MP3 to {config.music_dir}"
        if download_format == "audio"
        else f"Saved video to {config.video_dir}"
    )
    _set_job(job_id, status="done", message=done_msg, finished_at=datetime.now())


def start_download(
    url: str,
    config: VideoDownloadConfig,
    download_format: DownloadFormat | str | None = "video",
) -> tuple[bool, str, str | None]:
    fmt = normalize_download_format(
        download_format if isinstance(download_format, str) else "video"
    )
    ok, message = validate_video_url(url, config)
    if not ok:
        return False, message, None
    if fmt == "audio" and not ffmpeg_available():
        return False, "MP3 downloads need ffmpeg installed on the mini-PC", None
    available, ver_err = yt_dlp_available(config)
    if not available:
        return False, ver_err or "yt-dlp is not installed", None

    job_id = uuid.uuid4().hex[:12]
    job = DownloadJob(id=job_id, url=url.strip(), status="queued", format=fmt)
    with _JOB_LOCK:
        _JOBS[job_id] = job
        if len(_JOBS) > 50:
            oldest = sorted(_JOBS.values(), key=lambda j: j.started_at or datetime.min)
            for stale in oldest[: len(_JOBS) - 50]:
                _JOBS.pop(stale.id, None)

    thread = threading.Thread(
        target=_run_download,
        args=(job_id, url.strip(), config, fmt),
        name=f"video-download-{job_id}",
        daemon=True,
    )
    thread.start()
    return True, "Download started — refresh below for progress", job_id


def get_video_download_status(config: VideoDownloadConfig) -> dict:
    available, version_or_err = yt_dlp_available(config)
    video_root = Path(config.video_dir)
    music_root = Path(config.music_dir)
    dir_ok = (
        video_root.is_dir()
        or music_root.is_dir()
        or video_root.parent.is_dir()
        or music_root.parent.is_dir()
    )
    active = sum(1 for j in list_jobs() if j.status in ("queued", "running"))
    ff_ok = ffmpeg_available()
    return {
        "enabled": config.enabled,
        "yt_dlp_ok": available,
        "yt_dlp_version": version_or_err if available else None,
        "yt_dlp_error": None if available else version_or_err,
        "ffmpeg_ok": ff_ok,
        "video_dir": config.video_dir,
        "music_dir": config.music_dir,
        "download_dir": config.video_dir,
        "download_dir_ready": dir_ok,
        "allowed_hosts": config.allowed_hosts,
        "active_jobs": active,
        "jobs": list_jobs(),
    }
