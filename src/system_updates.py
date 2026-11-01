"""APT package update status and actions."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from src.config_loader import SystemUpdatesConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


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


def _invoke(config: SystemUpdatesConfig, action: str) -> tuple[dict[str, Any], str | None]:
    result = _run(["sudo", "-n", config.helper_script, action])
    stderr = (result.stderr or "").strip()
    try:
        data = _parse_helper_json(result.stdout or "")
    except json.JSONDecodeError:
        err = stderr or (result.stdout or "Invalid status from update helper").strip()
        return {}, err[:500] if err else "Invalid status from update helper"
    if result.returncode != 0 and not data:
        err = stderr or f"{action} failed"
        return {}, err
    return data, None


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


def _format_upgrade_message(data: dict[str, Any], *, full_upgrade: bool = False) -> str:
    upgraded = int(data.get("upgraded", 0))
    installed = int(data.get("installed", 0))
    removed = int(data.get("removed", 0))
    remaining = int(data.get("count", 0))
    not_upgraded = int(data.get("not_upgraded", remaining))
    parts: list[str] = []
    run_label = "apt full-upgrade" if full_upgrade else "apt upgrade"

    if upgraded > 0 or installed > 0 or removed > 0:
        detail: list[str] = []
        if upgraded:
            detail.append(f"{upgraded} upgraded")
        if installed:
            detail.append(f"{installed} newly installed")
        if removed:
            detail.append(f"{removed} removed")
        parts.append(f"Installed: {', '.join(detail)}.")
    else:
        parts.append(f"Nothing was installed this run ({run_label} made no changes).")

    if remaining > 0 or not_upgraded > 0:
        n = remaining if remaining else not_upgraded
        parts.append(f"{n} package(s) still listed as upgradable.")
        reasons: list[str] = []
        if data.get("phased"):
            reasons.append("Ubuntu may defer some updates (phasing)")
        if data.get("kept_back") and not full_upgrade:
            reasons.append("try Full upgrade for held-back packages")
        elif data.get("kept_back"):
            reasons.append("some packages may still be held or phased")
        if reasons:
            parts.append(" ".join(reasons) + ".")
    elif upgraded == 0 and installed == 0:
        parts = ["System is up to date — no packages needed installing."]

    if data.get("reboot_required"):
        parts.append("Reboot required.")
    return " ".join(parts)


def _apply_apt(config: SystemUpdatesConfig, action: str) -> tuple[bool, str, dict[str, Any]]:
    data, err = _invoke(config, action)
    if err:
        return False, err, {}
    if data.get("ok") is False:
        return False, "apt reported an error (check logs on the mini PC)", data
    full = action == "full-upgrade"
    return True, _format_upgrade_message(data, full_upgrade=full), data


def apply_system_updates(config: SystemUpdatesConfig) -> tuple[bool, str, dict[str, Any]]:
    return _apply_apt(config, "upgrade")


def apply_full_system_updates(config: SystemUpdatesConfig) -> tuple[bool, str, dict[str, Any]]:
    return _apply_apt(config, "full-upgrade")
