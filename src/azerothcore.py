"""AzerothCore component health checks."""

from __future__ import annotations

import socket
import subprocess
from typing import Any

import psutil

from src.config_loader import AzerothCoreConfig
from src.services import _batch_service_states


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def _process_info(name: str) -> dict[str, Any]:
    result = _run(["pgrep", "-x", name])
    if result.returncode != 0:
        return {"running": False, "pid": None, "memory_mb": None, "cpu_percent": None}
    try:
        pid = int(result.stdout.strip().splitlines()[0])
        proc = psutil.Process(pid)
        mem = proc.memory_info().rss / (1024 * 1024)
        cpu = proc.cpu_percent(interval=0.0)
        return {
            "running": True,
            "pid": pid,
            "memory_mb": round(mem, 0),
            "cpu_percent": round(cpu, 1),
        }
    except (psutil.Error, ValueError, IndexError):
        return {"running": True, "pid": None, "memory_mb": None, "cpu_percent": None}


def _level(*, running: bool, port: int | None, port_open: bool) -> tuple[str, str]:
    if running and (port is None or port_open):
        return "ok", "running"
    if running:
        return "amber", "starting"
    if port is not None and port_open:
        return "amber", "port only"
    return "warn", "stopped"


def _component(
    *,
    key: str,
    label: str,
    running: bool,
    port: int | None,
    port_open: bool,
    detail_parts: list[str],
) -> dict[str, Any]:
    level, state = _level(running=running, port=port, port_open=port_open)
    return {
        "key": key,
        "label": label,
        "level": level,
        "state": state,
        "running": running,
        "port": port,
        "port_open": port_open,
        "detail": " · ".join(detail_parts) if detail_parts else "—",
    }


def get_azerothcore_status(config: AzerothCoreConfig) -> dict[str, Any] | None:
    if not config.enabled:
        return None

    units = [u for u in (config.mysql_unit, config.systemd_unit) if u]
    unit_states = _batch_service_states(units)

    mysql_state = unit_states.get(config.mysql_unit, {}) if config.mysql_unit else {}
    mysql_active = mysql_state.get("active", "unknown")
    mysql_port_open = _port_open(config.mysql_port)
    mysql_ok = mysql_active == "active" and mysql_port_open
    mysql_detail = [f"systemd {mysql_active}"]
    if config.mysql_port:
        mysql_detail.append(f"port {config.mysql_port} {'open' if mysql_port_open else 'closed'}")

    auth = _process_info(config.auth_process)
    auth_port_open = _port_open(config.auth_port)
    auth_parts: list[str] = []
    if auth["pid"]:
        auth_parts.append(f"pid {auth['pid']}")
    if config.auth_port:
        auth_parts.append(f"port {config.auth_port} {'open' if auth_port_open else 'closed'}")
    if auth["memory_mb"] is not None:
        auth_parts.append(f"{auth['memory_mb']:.0f} MB")

    world = _process_info(config.world_process)
    world_port_open = _port_open(config.world_port)
    world_parts: list[str] = []
    if world["pid"]:
        world_parts.append(f"pid {world['pid']}")
    if config.world_port:
        world_parts.append(f"port {config.world_port} {'open' if world_port_open else 'closed'}")
    if world["memory_mb"] is not None:
        world_parts.append(f"{world['memory_mb']:.0f} MB")
    if world["running"] and world_port_open:
        world_parts.append("realm ready")
    elif world["running"]:
        world_parts.append("loading")

    systemd = unit_states.get(config.systemd_unit, {}) if config.systemd_unit else {}
    systemd_active = systemd.get("active", "unknown")
    tmux_auth = _run(["tmux", "has-session", "-t", config.auth_tmux_session]).returncode == 0
    tmux_world = _run(["tmux", "has-session", "-t", config.world_tmux_session]).returncode == 0
    wrapper_parts = [f"systemd {systemd_active}"]
    if tmux_auth or tmux_world:
        sessions = []
        if tmux_auth:
            sessions.append(config.auth_tmux_session)
        if tmux_world:
            sessions.append(config.world_tmux_session)
        wrapper_parts.append(f"tmux: {', '.join(sessions)}")

    components = [
        _component(
            key="mysql",
            label="MySQL database",
            running=mysql_active == "active",
            port=config.mysql_port,
            port_open=mysql_port_open,
            detail_parts=mysql_detail,
        ),
        _component(
            key="auth",
            label="Auth server",
            running=auth["running"],
            port=config.auth_port,
            port_open=auth_port_open,
            detail_parts=auth_parts,
        ),
        _component(
            key="world",
            label="World server",
            running=world["running"],
            port=config.world_port,
            port_open=world_port_open,
            detail_parts=world_parts,
        ),
        _component(
            key="wrapper",
            label="Start wrapper",
            running=systemd_active in ("active", "activating"),
            port=None,
            port_open=False,
            detail_parts=wrapper_parts,
        ),
    ]

    levels = [c["level"] for c in components[:3]]
    if "warn" in levels or not mysql_ok:
        overall = "warn"
    elif "amber" in levels:
        overall = "amber"
    elif all(c["running"] and (c["port"] is None or c["port_open"]) for c in components[:3]):
        overall = "ok"
    else:
        overall = "amber"

    ready = auth["running"] and auth_port_open and world["running"] and world_port_open and mysql_ok

    return {
        "label": config.label,
        "unit": config.systemd_unit,
        "manage": config.manage,
        "overall": overall,
        "ready": ready,
        "systemd_active": systemd_active,
        "components": components,
        "summary": _summary(ready, components),
    }


def _summary(ready: bool, components: list[dict[str, Any]]) -> str:
    if ready:
        return "Realm online — auth and world accepting connections"
    world = next(c for c in components if c["key"] == "world")
    auth = next(c for c in components if c["key"] == "auth")
    if world["running"] and not world["port_open"]:
        return "World server is loading (playerbots, maps, etc.)"
    if auth["running"] and not auth["port_open"]:
        return "Auth server is starting"
    if any(c["key"] in ("auth", "world") and c["running"] for c in components):
        return "Partially running — check component status below"
    return "Server stopped"
