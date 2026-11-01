"""ClamAV daemon status and manual scans."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from src.config_loader import ClamAvConfig

ScanScope = Literal["downloads", "shared"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _clamd_max_file_size_label() -> str | None:
    path = Path("/etc/clamav/clamd.conf")
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line.startswith("MaxFileSize "):
            continue
        return line.split(maxsplit=1)[1]
    return None


def get_clamav_status(config: ClamAvConfig) -> dict[str, Any]:
    daemon_active = _run(["systemctl", "is-active", config.daemon_unit]).stdout.strip() or "unknown"
    fresh_active = _run(["systemctl", "is-active", config.freshclam_unit]).stdout.strip() or "unknown"

    db_date: str | None = None
    daily = Path("/var/lib/clamav/daily.cld")
    if not daily.is_file():
        daily = Path("/var/lib/clamav/daily.cvd")
    if daily.is_file():
        db_date = daily.stat().st_mtime
        from datetime import datetime

        db_date = datetime.fromtimestamp(db_date).strftime("%Y-%m-%d %H:%M")

    log_tail: list[str] = []
    log_path = Path(config.scan_log)
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            log_tail = text.strip().splitlines()[-8:]
        except OSError:
            pass

    progress = get_clamav_scan_progress(config)

    overall = "ok" if daemon_active == "active" else "warn"
    return {
        "daemon_unit": config.daemon_unit,
        "freshclam_unit": config.freshclam_unit,
        "daemon_active": daemon_active,
        "freshclam_active": fresh_active,
        "overall": overall,
        "db_updated": db_date,
        "scan_log": str(log_path),
        "log_tail": log_tail,
        "scan_progress": progress,
        "max_file_size": _clamd_max_file_size_label(),
    }


def get_clamav_scan_progress(config: ClamAvConfig) -> dict[str, Any]:
    path = Path(config.scan_progress_file)
    if not path.is_file():
        return {"active": False, "state": "idle", "message": "", "percent": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"active": False, "state": "idle", "message": "", "percent": 0}
    for key, default in (
        ("active", False),
        ("state", "idle"),
        ("scope", ""),
        ("message", ""),
        ("total_files", 0),
        ("scanned_files", 0),
        ("infected", 0),
        ("errors", 0),
        ("percent", 0),
        ("current_file", None),
    ):
        data.setdefault(key, default)
    return data


def _parse_helper_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty", raw, 0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise


def _format_scan_message(data: dict[str, Any]) -> str:
    scope = data.get("scope") or "scan"
    infected = int(data.get("infected", 0))
    detail = (data.get("detail") or "").strip()
    target = data.get("target") or ""
    if infected > 0:
        return f"{scope.capitalize()} scan finished · {infected} infected (moved to quarantine) · {target}"
    if detail == "clean" or (isinstance(detail, str) and detail.startswith("clean (")):
        return f"{scope.capitalize()} scan finished · {detail} · {target}"
    if detail:
        return f"{scope.capitalize()} scan: {detail}"
    return f"{scope.capitalize()} scan finished"


def start_clamav_scan(config: ClamAvConfig, scope: ScanScope) -> tuple[bool, str]:
    if scope not in ("downloads", "shared"):
        return False, "Invalid scan scope"
    progress = get_clamav_scan_progress(config)
    if progress.get("active"):
        return False, "A scan is already running"
    result = _run(["sudo", "-n", config.helper_script, "start", scope])
    stderr = (result.stderr or "").strip()
    try:
        data = _parse_helper_json(result.stdout or "")
    except json.JSONDecodeError:
        err = stderr or (result.stdout or "Invalid response from scan helper").strip()
        return False, err[:500] if err else "Invalid response from scan helper"
    if not data.get("ok"):
        detail = (data.get("detail") or stderr or "Scan failed").strip()
        return False, detail[:500]
    return True, (data.get("detail") or "Scan started").strip()[:500]
