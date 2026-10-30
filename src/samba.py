"""Samba share status and user management (via sudo helper)."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from src.config_loader import SambaConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _admin(config: SambaConfig, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["sudo", "-n", config.admin_script, *args])


def _smbd_active(config: SambaConfig) -> str:
    return _run(["systemctl", "is-active", config.systemd_unit]).stdout.strip() or "unknown"


def list_samba_users(config: SambaConfig) -> tuple[list[str], str | None]:
    result = _admin(config, "list")
    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "list failed").strip()
    users = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return users, None


def add_samba_user(config: SambaConfig, username: str, password: str) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username (lowercase letters, digits, _ - only)"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    result = _admin(config, "add", user, password)
    if result.returncode == 0:
        return True, f"Added Samba user {user}"
    return False, (result.stderr or result.stdout or "add failed").strip()


def remove_samba_user(config: SambaConfig, username: str) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username"
    result = _admin(config, "remove", user)
    if result.returncode == 0:
        return True, f"Removed Samba user {user}"
    return False, (result.stderr or result.stdout or "remove failed").strip()


def get_samba_status(config: SambaConfig) -> dict[str, Any]:
    active = _smbd_active(config)
    users, err = list_samba_users(config)
    overall = "ok" if active == "active" else "warn"
    return {
        "unit": config.systemd_unit,
        "active": active,
        "overall": overall,
        "share_name": config.share_name,
        "share_path": config.share_path,
        "unc_path": config.unc_path,
        "users": users,
        "users_error": err,
    }
