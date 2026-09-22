"""Systemd service status and management."""

from __future__ import annotations

import socket
import subprocess
from typing import Any

from src.config_loader import ServiceConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _systemctl(*args: str) -> str:
    result = _run(["systemctl", *args])
    return (result.stdout or result.stderr or "").strip()


def get_hostname_label(configured: str | None) -> str:
    if configured:
        return configured
    return socket.gethostname()


def format_uptime(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def inspect_service(unit: str) -> dict[str, Any]:
    active = _systemctl("is-active", unit)
    enabled = _systemctl("is-enabled", unit)
    level = "ok"
    if active not in ("active", "activating"):
        level = "warn" if active in ("inactive", "failed") else "amber"
    return {
        "unit": unit,
        "active": active,
        "enabled": enabled,
        "level": level,
    }


def list_services(configs: list[ServiceConfig]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        row = inspect_service(cfg.unit)
        row["label"] = cfg.label
        row["manage"] = cfg.manage
        rows.append(row)
    return rows


def restart_service(unit: str) -> tuple[bool, str]:
    result = _run(["sudo", "-n", "systemctl", "restart", unit])
    if result.returncode == 0:
        return True, f"Restarted {unit}"
    msg = (result.stderr or result.stdout or "restart failed").strip()
    return False, msg
