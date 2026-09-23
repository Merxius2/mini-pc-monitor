"""Mini-PC sleep schedule — read and update systemd timers."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config_loader import SleepScheduleConfig

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CALENDAR_TIME_RE = re.compile(r"(\d{2}:\d{2})")
_WAKE_RE = re.compile(r'^WAKE="(\d{2}:\d{2})"', re.MULTILINE)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _sudo_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(["sudo", "-n", *cmd])


def validate_time(value: str) -> bool:
    return bool(_TIME_RE.match(value.strip()))


def _parse_calendar(raw: str) -> str | None:
    match = _CALENDAR_TIME_RE.search(raw)
    return match.group(1) if match else None


def _read_wake_time(script_path: Path) -> str | None:
    if not script_path.is_file():
        return None
    match = _WAKE_RE.search(script_path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _timer_props(timer: str) -> dict[str, str]:
    result = _run(
        [
            "systemctl",
            "show",
            timer,
            "-p",
            "ActiveState",
            "-p",
            "UnitFileState",
            "-p",
            "TimersCalendar",
            "-p",
            "NextElapseUSecRealtime",
            "--no-pager",
        ]
    )
    props: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            props[key] = value
    return props


def _service_active(unit: str) -> bool:
    result = _run(["systemctl", "is-active", unit])
    return (result.stdout or "").strip() == "active"


def _next_occurrence(time_hhmm: str, *, now: datetime | None = None) -> datetime:
    now = now or datetime.now().astimezone()
    hour, minute = (int(part) for part in time_hhmm.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _phase(
    *,
    enabled: bool,
    keep_awake_active: bool,
    sleep_time: str | None,
    wake_time: str | None,
    now: datetime | None = None,
) -> str:
    if not enabled:
        return "disabled"
    if keep_awake_active:
        return "daytime"
    now = now or datetime.now().astimezone()
    if sleep_time and wake_time:
        sleep_dt = now.replace(
            hour=int(sleep_time[:2]),
            minute=int(sleep_time[3:5]),
            second=0,
            microsecond=0,
        )
        wake_dt = now.replace(
            hour=int(wake_time[:2]),
            minute=int(wake_time[3:5]),
            second=0,
            microsecond=0,
        )
        if wake_dt < sleep_dt:
            if wake_dt <= now < sleep_dt:
                return "daytime"
            return "nighttime"
        if sleep_dt <= now < wake_dt:
            return "nighttime"
        return "daytime"
    return "unknown"


def get_schedule_status(config: SleepScheduleConfig) -> dict[str, Any]:
    nightly = _timer_props(config.nightly_off_timer)
    wake_timer = _timer_props(config.keep_awake_timer)
    keep_awake_active = _service_active(config.keep_awake_service)

    sleep_time = _parse_calendar(nightly.get("TimersCalendar", ""))
    wake_time = _read_wake_time(Path(config.suspend_script))
    if wake_time is None:
        wake_time = _parse_calendar(wake_timer.get("TimersCalendar", ""))

    nightly_enabled = nightly.get("UnitFileState") == "enabled"
    wake_enabled = wake_timer.get("UnitFileState") == "enabled"
    enabled = nightly_enabled and wake_enabled

    next_sleep = nightly.get("NextElapseUSecRealtime") or ""
    next_wake = wake_timer.get("NextElapseUSecRealtime") or ""
    if enabled and sleep_time and not next_sleep:
        next_sleep = _next_occurrence(sleep_time).strftime("%a %d %b %Y · %H:%M")
    if enabled and wake_time and not next_wake:
        next_wake = _next_occurrence(wake_time).strftime("%a %d %b %Y · %H:%M")

    phase = _phase(
        enabled=enabled,
        keep_awake_active=keep_awake_active,
        sleep_time=sleep_time,
        wake_time=wake_time,
    )

    return {
        "enabled": enabled,
        "manage": config.manage,
        "sleep_time": sleep_time or "—",
        "wake_time": wake_time or "—",
        "next_sleep": next_sleep or "—",
        "next_wake": next_wake or "—",
        "keep_awake_active": keep_awake_active,
        "phase": phase,
        "nightly_timer": config.nightly_off_timer,
        "wake_timer": config.keep_awake_timer,
    }


def _write_drop_in(timer: str, sleep_or_wake_time: str) -> tuple[bool, str]:
    drop_dir = f"/etc/systemd/system/{timer}.d"
    drop_file = f"{drop_dir}/mini-pc-monitor.conf"
    content = f"[Timer]\nOnCalendar=*-*-* {sleep_or_wake_time}:00\n"
    mkdir = _sudo_run(["mkdir", "-p", drop_dir])
    if mkdir.returncode != 0:
        msg = (mkdir.stderr or mkdir.stdout or "mkdir failed").strip()
        return False, msg
    write = subprocess.run(
        ["sudo", "-n", "tee", drop_file],
        input=content,
        capture_output=True,
        text=True,
        check=False,
    )
    if write.returncode != 0:
        msg = (write.stderr or write.stdout or "write failed").strip()
        return False, msg
    return True, drop_file


def _update_wake_in_script(script_path: Path, wake_time: str) -> tuple[bool, str]:
    if not script_path.is_file():
        return False, f"Script not found: {script_path}"
    text = script_path.read_text(encoding="utf-8")
    if not _WAKE_RE.search(text):
        return False, "Wake time marker not found in suspend script"
    updated = _WAKE_RE.sub(f'WAKE="{wake_time}"', text, count=1)
    write = subprocess.run(
        ["sudo", "-n", "tee", str(script_path)],
        input=updated,
        capture_output=True,
        text=True,
        check=False,
    )
    if write.returncode != 0:
        msg = (write.stderr or write.stdout or "script update failed").strip()
        return False, msg
    return True, str(script_path)


def apply_schedule(
    config: SleepScheduleConfig,
    *,
    sleep_time: str,
    wake_time: str,
) -> tuple[bool, str]:
    if not config.manage:
        return False, "Schedule management disabled in config"
    sleep_time = sleep_time.strip()
    wake_time = wake_time.strip()
    if not validate_time(sleep_time) or not validate_time(wake_time):
        return False, "Use 24-hour times like 21:00 and 09:00"
    if sleep_time == wake_time:
        return False, "Sleep and wake times must differ"

    ok, msg = _write_drop_in(config.nightly_off_timer, sleep_time)
    if not ok:
        return False, msg
    ok, msg = _write_drop_in(config.keep_awake_timer, wake_time)
    if not ok:
        return False, msg
    ok, msg = _update_wake_in_script(Path(config.suspend_script), wake_time)
    if not ok:
        return False, msg

    reload = _sudo_run(["systemctl", "daemon-reload"])
    if reload.returncode != 0:
        msg = (reload.stderr or reload.stdout or "daemon-reload failed").strip()
        return False, msg

    return True, f"Schedule updated — sleep {sleep_time}, wake {wake_time}"


def set_schedule_enabled(config: SleepScheduleConfig, enabled: bool) -> tuple[bool, str]:
    if not config.manage:
        return False, "Schedule management disabled in config"
    action = "enable" if enabled else "disable"
    for timer in (config.nightly_off_timer, config.keep_awake_timer):
        result = _sudo_run(["systemctl", action, "--now", timer])
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or f"{action} failed").strip()
            return False, msg
    if not enabled:
        _sudo_run(["systemctl", "stop", config.keep_awake_service])
        return True, "Sleep schedule disabled"
    status = get_schedule_status(config)
    if status["phase"] == "daytime":
        start = _sudo_run(["systemctl", "start", config.keep_awake_service])
        if start.returncode != 0:
            msg = (start.stderr or start.stdout or "start keep-awake failed").strip()
            return False, msg
    return True, "Sleep schedule enabled"


def _nightly_off_service(config: SleepScheduleConfig) -> str:
    if config.nightly_off_service:
        return config.nightly_off_service
    if config.nightly_off_timer.endswith(".timer"):
        return config.nightly_off_timer[: -len(".timer")] + ".service"
    return "minipc-nightly-off.service"


def suspend_now(config: SleepScheduleConfig) -> tuple[bool, str]:
    if not config.manage:
        return False, "Power management disabled in config"
    _sudo_run(["systemctl", "stop", config.keep_awake_service])
    service = _nightly_off_service(config)
    result = _sudo_run(["systemctl", "start", "--no-block", service])
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "suspend failed").strip()
        return False, msg
    wake_time = _read_wake_time(Path(config.suspend_script)) or "scheduled wake time"
    return True, f"Suspending now — RTC wake at {wake_time}"
