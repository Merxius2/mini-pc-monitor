"""Persist and restore systemd active states for dashboard-managed services."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from src.config_loader import ServiceStateConfig, Settings, manageable_service_units


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _unit_active(unit: str) -> bool:
    state = (_run(["systemctl", "is-active", unit]).stdout or "").strip()
    return state in ("active", "activating")


def _state_path(config: ServiceStateConfig) -> Path:
    return Path(config.state_file)


def load_state(config: ServiceStateConfig) -> dict[str, Any]:
    path = _state_path(config)
    if not path.is_file():
        return {"version": 1, "units": {}, "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "units": {}, "updated_at": None}
    if not isinstance(data.get("units"), dict):
        data["units"] = {}
    return data


def _write_state(config: ServiceStateConfig, data: dict[str, Any]) -> None:
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = 1
    data["updated_at"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def set_unit_desired(config: ServiceStateConfig, unit: str, active: bool) -> None:
    if not config.enabled or unit in config.protect_units:
        return
    data = load_state(config)
    data["units"][unit] = bool(active)
    _write_state(config, data)


def snapshot_managed(settings: Settings) -> None:
    config = settings.service_state
    if not config.enabled:
        return
    allowed = manageable_service_units(settings)
    data = load_state(config)
    units: dict[str, bool] = {}
    for unit in sorted(allowed):
        if unit in config.protect_units:
            continue
        units[unit] = _unit_active(unit)
    data["units"] = units
    _write_state(config, data)


def _storage_ready() -> bool:
    return _run(["mountpoint", "-q", "/mnt/storage"]).returncode == 0


def _control(unit: str, action: str) -> bool:
    return _run(["systemctl", action, unit]).returncode == 0


def restore_saved_state(settings: Settings) -> tuple[int, int]:
    """Apply saved desired active states. Returns (started, stopped) counts."""
    config = settings.service_state
    if not config.enabled or not config.restore_on_boot:
        return 0, 0
    data = load_state(config)
    desired: dict[str, bool] = data.get("units") or {}
    if not desired:
        return 0, 0

    stopped = 0
    started = 0
    storage_units = set(config.storage_dependent_units)

    for unit, want_active in desired.items():
        if unit in config.protect_units:
            continue
        if not want_active:
            if _unit_active(unit):
                if _control(unit, "stop"):
                    stopped += 1
            continue

    for unit, want_active in desired.items():
        if unit in config.protect_units or not want_active:
            continue
        if unit in storage_units and not _storage_ready():
            continue
        if not _unit_active(unit):
            if _control(unit, "start"):
                started += 1
            if unit == "smbd.service" and _storage_ready():
                _control("nmbd.service", "start")

    return started, stopped
