"""ClamAV full-scan systemd timer schedule."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config_loader import ClamAvConfig, ClamAvScheduleConfig
from src.sleep_schedule import validate_time

_TIME_IN_DROPIN = re.compile(r"OnCalendar=\*-\*-\* (\d{1,2}:\d{2}):\d{2}")
_SCOPE_IN_DROPIN = re.compile(r'MINIPC_CLAM_SCHEDULE_SCOPE=(downloads|shared)')


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _sudo_run(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["sudo", "-n", *args]
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
    )


def _timer_props(timer: str) -> dict[str, str]:
    result = _run(
        [
            "systemctl",
            "show",
            timer,
            "-p",
            "UnitFileState",
            "-p",
            "NextElapseUSecRealtime",
            "-p",
            "ActiveState",
            "--no-pager",
        ]
    )
    props: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value
    return props


def _read_drop_in(timer: str) -> tuple[str | None, str | None]:
    path = Path(f"/etc/systemd/system/{timer}.d/mini-pc-monitor.conf")
    if not path.is_file():
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    time_match = _TIME_IN_DROPIN.search(text)
    scope_match = _SCOPE_IN_DROPIN.search(text)
    time_val = time_match.group(1) if time_match else None
    scope_val = scope_match.group(1) if scope_match else None
    return time_val, scope_val


def _read_service_scope(service: str) -> str | None:
    path = Path(f"/etc/systemd/system/{service}.d/mini-pc-monitor.conf")
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _SCOPE_IN_DROPIN.search(text)
    return match.group(1) if match else None


def _format_next(raw: str) -> str:
    if not raw or raw in ("n/a", "—"):
        return "—"
    try:
        if raw.endswith(" UTC"):
            raw = raw[: -len(" UTC")]
        dt = datetime.strptime(raw, "%a %Y-%m-%d %H:%M:%S %Z")
        return dt.strftime("%a %d %b %Y · %H:%M")
    except ValueError:
        return raw


def get_clamav_schedule_status(config: ClamAvConfig) -> dict[str, Any]:
    sched = config.schedule
    timer_props = _timer_props(sched.timer_unit)
    enabled = timer_props.get("UnitFileState") == "enabled"
    drop_time, drop_scope = _read_drop_in(sched.timer_unit)
    service_scope = _read_service_scope(sched.service_unit)
    time_str = drop_time or sched.time
    scope = service_scope or drop_scope or sched.scope
    next_run = _format_next(timer_props.get("NextElapseUSecRealtime", ""))
    return {
        "manage": sched.manage,
        "enabled": enabled,
        "time": time_str,
        "scope": scope,
        "timer_unit": sched.timer_unit,
        "service_unit": sched.service_unit,
        "next_run": next_run,
    }


def _write_file(path: str, content: str) -> tuple[bool, str]:
    mkdir = _sudo_run(["mkdir", "-p", str(Path(path).parent)])
    if mkdir.returncode != 0:
        return False, (mkdir.stderr or mkdir.stdout or "mkdir failed").strip()
    write = _sudo_run(["tee", path], input_text=content)
    if write.returncode != 0:
        return False, (write.stderr or write.stdout or "write failed").strip()
    return True, path


def apply_clamav_schedule(
    config: ClamAvConfig,
    *,
    time_str: str,
    scope: str,
) -> tuple[bool, str]:
    sched = config.schedule
    if not sched.manage:
        return False, "ClamAV schedule management disabled in config"
    time_str = time_str.strip()
    scope = scope.strip().lower()
    if not validate_time(time_str):
        return False, "Use 24-hour time like 03:30"
    if scope not in ("downloads", "shared"):
        return False, "Scope must be downloads or shared"

    timer_drop = f"/etc/systemd/system/{sched.timer_unit}.d/mini-pc-monitor.conf"
    timer_content = (
        "[Timer]\n"
        "OnCalendar=\n"
        f"OnCalendar=*-*-* {time_str}:00\n"
    )
    ok, msg = _write_file(timer_drop, timer_content)
    if not ok:
        return False, msg

    service_drop = f"/etc/systemd/system/{sched.service_unit}.d/mini-pc-monitor.conf"
    service_content = (
        "[Service]\n"
        f"Environment=MINIPC_CLAM_SCHEDULE_SCOPE={scope}\n"
        f'ExecStart=\n'
        f"ExecStart=/usr/local/sbin/minipc-clamscan-admin start {scope}\n"
    )
    ok, msg = _write_file(service_drop, service_content)
    if not ok:
        return False, msg

    reload = _sudo_run(["systemctl", "daemon-reload"])
    if reload.returncode != 0:
        return False, (reload.stderr or reload.stdout or "daemon-reload failed").strip()

    restart = _sudo_run(["systemctl", "restart", sched.timer_unit])
    if restart.returncode != 0:
        return False, (restart.stderr or restart.stdout or "timer restart failed").strip()

    label = "shared folder" if scope == "shared" else "downloads"
    return True, f"Full scan scheduled daily at {time_str} ({label})"


def set_clamav_schedule_enabled(config: ClamAvConfig, enabled: bool) -> tuple[bool, str]:
    sched = config.schedule
    if not sched.manage:
        return False, "ClamAV schedule management disabled in config"
    action = "enable" if enabled else "disable"
    result = _sudo_run(["systemctl", action, "--now", sched.timer_unit])
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or f"systemctl {action} failed").strip()
        return False, msg
    if enabled:
        status = get_clamav_schedule_status(config)
        return True, f"Scheduled scans enabled · next run {status['next_run']}"
    return True, "Scheduled full scans disabled"
