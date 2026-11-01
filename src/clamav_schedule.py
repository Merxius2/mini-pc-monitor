"""ClamAV full-scan systemd timer schedule."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config_loader import ClamAvConfig, ClamAvScheduleConfig
from src.sleep_schedule import validate_time

DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABEL = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
DAY_TO_SYSTEMD = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
SYSTEMD_TO_DAY = {v: k for k, v in DAY_TO_SYSTEMD.items()}
_DAY_ALIASES = {
    "mon": "mon",
    "monday": "mon",
    "tue": "tue",
    "tues": "tue",
    "tuesday": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "thu": "thu",
    "thur": "thu",
    "thurs": "thu",
    "thursday": "thu",
    "fri": "fri",
    "friday": "fri",
    "sat": "sat",
    "saturday": "sat",
    "sun": "sun",
    "sunday": "sun",
}

_SCOPE_IN_DROPIN = re.compile(r"MINIPC_CLAM_SCHEDULE_SCOPE=(downloads|shared)")


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


def default_schedule_days() -> list[str]:
    return list(DAY_ORDER)


def normalize_days(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = _DAY_ALIASES.get(item.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        picked.append(key)
    return [d for d in DAY_ORDER if d in seen]


def is_all_days(days: list[str]) -> bool:
    norm = normalize_days(days)
    return len(norm) == len(DAY_ORDER)


def format_days_label(days: list[str]) -> str:
    norm = normalize_days(days)
    if not norm:
        return "—"
    if is_all_days(norm):
        return "Every day"
    return ", ".join(DAY_LABEL[d] for d in DAY_ORDER if d in norm)


def timer_dropin_content(time_str: str, days: list[str]) -> str:
    norm = normalize_days(days)
    if not norm:
        raise ValueError("no days selected")
    hour, minute = time_str.split(":", 1)
    stamp = f"{hour}:{minute}:00"
    lines = ["[Timer]", "OnCalendar="]
    if is_all_days(norm):
        lines.append(f"OnCalendar=*-*-* {stamp}")
    else:
        for day in DAY_ORDER:
            if day in norm:
                lines.append(f"OnCalendar={DAY_TO_SYSTEMD[day]} *-*-* {stamp}")
    return "\n".join(lines) + "\n"


def parse_timer_dropin(text: str) -> tuple[str | None, list[str] | None]:
    times: set[str] = set()
    days_found: set[str] = set()
    all_days_marker = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("OnCalendar=") or line == "OnCalendar=":
            continue
        cal = line.removeprefix("OnCalendar=").strip()
        parts = cal.split()
        if len(parts) == 2 and parts[0] == "*-*-*":
            all_days_marker = True
            times.add(parts[1][:5])
            continue
        if len(parts) == 3 and parts[1] == "*-*-*":
            times.add(parts[2][:5])
            day = SYSTEMD_TO_DAY.get(parts[0])
            if day:
                days_found.add(day)
    if not times:
        return None, None
    time_str = sorted(times)[0]
    if all_days_marker or len(days_found) >= len(DAY_ORDER):
        return time_str, default_schedule_days()
    if not days_found:
        return time_str, None
    return time_str, [d for d in DAY_ORDER if d in days_found]


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


def _read_timer_drop_in(timer: str) -> tuple[str | None, list[str] | None]:
    path = Path(f"/etc/systemd/system/{timer}.d/mini-pc-monitor.conf")
    if not path.is_file():
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    return parse_timer_dropin(text)


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


def _day_options(selected: list[str]) -> list[dict[str, Any]]:
    picked = set(normalize_days(selected))
    return [
        {"value": day, "label": DAY_LABEL[day], "checked": day in picked}
        for day in DAY_ORDER
    ]


def get_clamav_schedule_status(config: ClamAvConfig) -> dict[str, Any]:
    sched = config.schedule
    timer_props = _timer_props(sched.timer_unit)
    enabled = timer_props.get("UnitFileState") == "enabled"
    drop_time, drop_days = _read_timer_drop_in(sched.timer_unit)
    service_scope = _read_service_scope(sched.service_unit)
    time_str = drop_time or sched.time
    scope = service_scope or sched.scope
    days = drop_days if drop_days is not None else normalize_days(sched.days) or default_schedule_days()
    next_run = _format_next(timer_props.get("NextElapseUSecRealtime", ""))
    return {
        "manage": sched.manage,
        "enabled": enabled,
        "time": time_str,
        "scope": scope,
        "days": days,
        "days_label": format_days_label(days),
        "day_options": _day_options(days),
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
    days: list[str] | None = None,
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
    norm_days = normalize_days(days if days is not None else sched.days)
    if not norm_days:
        return False, "Pick at least one day of the week"

    timer_drop = f"/etc/systemd/system/{sched.timer_unit}.d/mini-pc-monitor.conf"
    try:
        timer_content = timer_dropin_content(time_str, norm_days)
    except ValueError:
        return False, "Pick at least one day of the week"
    ok, msg = _write_file(timer_drop, timer_content)
    if not ok:
        return False, msg

    service_drop = f"/etc/systemd/system/{sched.service_unit}.d/mini-pc-monitor.conf"
    service_content = (
        "[Service]\n"
        f"Environment=MINIPC_CLAM_SCHEDULE_SCOPE={scope}\n"
        "ExecStart=\n"
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
    when = format_days_label(norm_days)
    return True, f"Full scan scheduled {when} at {time_str} ({label})"


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
