"""ClamAV daemon status."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from src.config_loader import ClamAvConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


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
    }
