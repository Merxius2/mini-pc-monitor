"""Online video downloads via yt-dlp for configured allowed hosts."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlparse

from src.config_loader import VideoDownloadConfig

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, "DownloadJob"] = {}
_DELETE_TIMERS: dict[str, threading.Timer] = {}

DownloadFormat = Literal["video", "audio"]


@dataclass
class DownloadJob:
    id: str
    url: str
    status: str  # queued | running | done | error
    format: DownloadFormat = "video"
    push_to_device: bool = False
    delete_after_push: bool = False
    output_category: str = ""
    output_name: str = ""
    storage_purge_at: datetime | None = None
    storage_purged: bool = False
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def file_url(self) -> str | None:
        if self.status != "done" or not self.output_name or not self.output_category:
            return None
        return (
            f"/video-download/files/{self.output_category}/"
            f"{quote(self.output_name, safe='')}"
        )


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


def parse_form_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def parse_push_mode(raw: str | None) -> tuple[bool, bool]:
    """Return (push_to_device, delete_after_push). Purge only when push is on."""
    mode = (raw or "off").strip().lower()
    if mode in ("push_purge", "push+purge", "push_and_purge"):
        return True, True
    if mode in ("push", "device", "on", "true", "1"):
        return True, False
    return False, False


def media_category_for_format(download_format: DownloadFormat) -> str:
    return "music" if download_format == "audio" else "video"


def resolve_media_file(
    config: VideoDownloadConfig,
    category: str,
    file_path: str,
) -> Path | None:
    if category not in ("video", "music"):
        return None
    root = Path(
        config.video_dir if category == "video" else config.music_dir
    ).resolve()
    if not file_path or file_path.startswith("/") or ".." in file_path.split("/"):
        return None
    try:
        target = (root / file_path).resolve()
        target.relative_to(root)
    except (OSError, ValueError):
        return None
    if not target.is_file():
        return None
    return target


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
    for timer in list(_DELETE_TIMERS.values()):
        timer.cancel()
    _DELETE_TIMERS.clear()


def _cancel_delete_timer(job_id: str) -> None:
    timer = _DELETE_TIMERS.pop(job_id, None)
    if timer:
        timer.cancel()


def _purge_file_from_storage(
    config: VideoDownloadConfig,
    job_id: str,
    category: str,
    output_name: str,
) -> None:
    target = resolve_media_file(config, category, output_name)
    removed = False
    if target:
        try:
            target.unlink()
            removed = True
        except OSError:
            removed = False
        for extra in (target.with_suffix(".jpg"), target.with_suffix(".webp")):
            if extra.is_file() and extra != target:
                try:
                    extra.unlink()
                except OSError:
                    pass
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.storage_purged = removed
        if removed:
            suffix = " · Removed from storage"
            if suffix not in (job.message or ""):
                job.message = (job.message or "") + suffix
        else:
            suffix = " · Storage cleanup skipped (file missing)"
            if suffix not in (job.message or ""):
                job.message = (job.message or "") + suffix


def schedule_storage_delete(
    config: VideoDownloadConfig,
    job_id: str,
    category: str,
    output_name: str,
    delay_seconds: int,
) -> datetime | None:
    if delay_seconds <= 0 or not output_name or not category:
        return None
    _cancel_delete_timer(job_id)
    purge_at = datetime.now().timestamp() + delay_seconds
    purge_dt = datetime.fromtimestamp(purge_at)

    def _fire() -> None:
        _DELETE_TIMERS.pop(job_id, None)
        _purge_file_from_storage(config, job_id, category, output_name)

    timer = threading.Timer(delay_seconds, _fire)
    timer.daemon = True
    timer.name = f"video-download-purge-{job_id}"
    _DELETE_TIMERS[job_id] = timer
    timer.start()
    return purge_dt


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


def _newest_file_since(directory: Path, since: datetime) -> Path | None:
    if not directory.is_dir():
        return None
    cutoff = since.timestamp() - 1.0
    newest: tuple[float, Path] | None = None
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".part", ".ytdl", ".temp"}:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        if newest is None or mtime > newest[0]:
            newest = (mtime, path)
    return newest[1] if newest else None


def _output_name_from_yt_dlp(
    path_file: Path,
    out_dir: Path,
    started_at: datetime,
) -> str:
    if path_file.is_file():
        try:
            lines = [
                ln.strip()
                for ln in path_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if ln.strip()
            ]
        except OSError:
            lines = []
        for line in reversed(lines):
            candidate = Path(line.strip('"\''))
            try:
                if candidate.is_file():
                    candidate.resolve().relative_to(out_dir.resolve())
                    return candidate.name
            except (OSError, ValueError):
                continue
    fallback = _newest_file_since(out_dir, started_at)
    return fallback.name if fallback else ""


def _run_download(
    job_id: str,
    url: str,
    config: VideoDownloadConfig,
    download_format: DownloadFormat,
) -> None:
    started = datetime.now()
    _set_job(job_id, status="running", started_at=started)
    out_dir = output_dir_for_format(config, download_format)
    out_dir.mkdir(parents=True, exist_ok=True)
    path_file = Path(tempfile.gettempdir()) / f"vd-path-{job_id}.txt"
    path_file.unlink(missing_ok=True)
    cmd = build_yt_dlp_download_command(url, config, download_format)
    url_arg = cmd.pop()
    cmd.extend(["--print-to-file", "after_move:filepath", str(path_file), url_arg])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=config.download_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        path_file.unlink(missing_ok=True)
        _set_job(
            job_id,
            status="error",
            message=f"Timed out after {config.download_timeout_seconds}s",
            finished_at=datetime.now(),
        )
        return
    except OSError as exc:
        path_file.unlink(missing_ok=True)
        _set_job(job_id, status="error", message=str(exc), finished_at=datetime.now())
        return

    if result.returncode != 0:
        path_file.unlink(missing_ok=True)
        err = (result.stderr or result.stdout or "Download failed").strip()
        err = re.sub(r"\s+", " ", err)
        if len(err) > 400:
            err = err[:397] + "..."
        _set_job(job_id, status="error", message=err, finished_at=datetime.now())
        return

    category = media_category_for_format(download_format)
    output_name = _output_name_from_yt_dlp(path_file, out_dir, started)
    path_file.unlink(missing_ok=True)
    done_msg = (
        f"Saved MP3 to {config.music_dir}"
        if download_format == "audio"
        else f"Saved video to {config.video_dir}"
    )
    purge_at: datetime | None = None
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        delete_after = bool(job and job.delete_after_push and job.push_to_device)
    if delete_after and output_name:
        minutes = max(1, config.delete_after_push_seconds // 60)
        purge_at = schedule_storage_delete(
            config,
            job_id,
            category,
            output_name,
            config.delete_after_push_seconds,
        )
        if purge_at:
            done_msg += f" · Will remove from storage in {minutes} min"
    _set_job(
        job_id,
        status="done",
        message=done_msg,
        finished_at=datetime.now(),
        output_category=category,
        output_name=output_name,
        storage_purge_at=purge_at,
    )


def start_download(
    url: str,
    config: VideoDownloadConfig,
    download_format: DownloadFormat | str | None = "video",
    push_to_device: bool = False,
    delete_after_push: bool = False,
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
    job = DownloadJob(
        id=job_id,
        url=url.strip(),
        status="queued",
        format=fmt,
        push_to_device=push_to_device,
        delete_after_push=delete_after_push and push_to_device,
    )
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
