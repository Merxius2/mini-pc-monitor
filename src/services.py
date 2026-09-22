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


def _batch_service_states(units: list[str]) -> dict[str, dict[str, str]]:
    if not units:
        return {}
    result = _run(
        [
            "systemctl",
            "show",
            *units,
            "-p",
            "ActiveState",
            "-p",
            "UnitFileState",
            "--no-pager",
        ]
    )
    blocks = [block.strip() for block in (result.stdout or "").strip().split("\n\n") if block.strip()]
    states: dict[str, dict[str, str]] = {}
    for unit, block in zip(units, blocks):
        props = dict(
            line.split("=", 1)
            for line in block.splitlines()
            if "=" in line
        )
        states[unit] = {
            "active": props.get("ActiveState", "unknown"),
            "enabled": props.get("UnitFileState", "unknown"),
        }
    for unit in units:
        states.setdefault(unit, {"active": "unknown", "enabled": "unknown"})
    return states


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
    if not configs:
        return []
    states = _batch_service_states([cfg.unit for cfg in configs])
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        state = states[cfg.unit]
        active = state["active"]
        level = "ok"
        if active not in ("active", "activating"):
            level = "warn" if active in ("inactive", "failed") else "amber"
        rows.append(
            {
                "unit": cfg.unit,
                "active": active,
                "enabled": state["enabled"],
                "level": level,
                "label": cfg.label,
                "manage": cfg.manage,
            }
        )
    return rows


def _control_service(unit: str, action: str) -> tuple[bool, str]:
    result = _run(["sudo", "-n", "systemctl", action, unit])
    if result.returncode == 0:
        label = action.capitalize()
        return True, f"{label}ed {unit}" if action != "stop" else f"Stopped {unit}"
    msg = (result.stderr or result.stdout or f"{action} failed").strip()
    return False, msg


def start_service(unit: str) -> tuple[bool, str]:
    return _control_service(unit, "start")


def stop_service(unit: str) -> tuple[bool, str]:
    return _control_service(unit, "stop")


def restart_service(unit: str) -> tuple[bool, str]:
    return _control_service(unit, "restart")
