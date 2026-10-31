"""APT package update status and actions."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from src.config_loader import SystemUpdatesConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _invoke(config: SystemUpdatesConfig, action: str) -> tuple[dict[str, Any], str | None]:
    result = _run(["sudo", "-n", config.helper_script, action])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or f"{action} failed").strip()
        return {}, err
    try:
        return json.loads(result.stdout or "{}"), None
    except json.JSONDecodeError:
        return {}, "Invalid status from update helper"


def get_system_updates_status(config: SystemUpdatesConfig) -> dict[str, Any]:
    data, err = _invoke(config, "status")
    count = int(data.get("count", 0))
    reboot = bool(data.get("reboot_required"))
    overall = "ok"
    if reboot:
        overall = "amber"
    elif count > 0:
        overall = "warn"
    packages = data.get("packages") or []
    return {
        "enabled": config.enabled,
        "overall": overall,
        "count": count,
        "packages": packages[: config.max_packages_shown],
        "packages_truncated": len(packages) > config.max_packages_shown,
        "reboot_required": reboot,
        "reboot_hint": data.get("reboot_hint"),
        "error": err,
    }


def refresh_system_updates(config: SystemUpdatesConfig) -> tuple[bool, str, dict[str, Any]]:
    data, err = _invoke(config, "refresh")
    if err:
        return False, err, {}
    count = int(data.get("count", 0))
    return True, f"Update index refreshed · {count} upgrade(s) available", data


def apply_system_updates(config: SystemUpdatesConfig) -> tuple[bool, str, dict[str, Any]]:
    data, err = _invoke(config, "upgrade")
    if err:
        return False, err, {}
    count = int(data.get("count", 0))
    reboot = bool(data.get("reboot_required"))
    msg = f"Upgrade finished · {count} package(s) still pending"
    if count == 0:
        msg = "System is up to date"
    if reboot:
        msg += " · reboot required"
    return True, msg, data
