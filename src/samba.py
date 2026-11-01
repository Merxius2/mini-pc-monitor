"""Samba share status and user management (via sudo helper)."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Literal

from src.config_loader import SambaConfig

SambaAccess = Literal["read", "write"]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _admin(config: SambaConfig, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["sudo", "-n", config.admin_script, *args])


def _smbd_active(config: SambaConfig) -> str:
    return _run(["systemctl", "is-active", config.systemd_unit]).stdout.strip() or "unknown"


def smb_connect_url(unc_path: str) -> str:
    """LAN URL for QR codes and mobile SMB clients (smb://host/share)."""
    path = unc_path.strip()
    if path.startswith("//"):
        return "smb:" + path
    if path.startswith("\\\\"):
        normalized = path.replace("\\", "/").lstrip("/")
        return f"smb://{normalized}"
    if path.startswith("smb://"):
        return path
    return f"smb://{path.lstrip('/')}"


def _parse_access(value: str) -> SambaAccess:
    return "read" if value.strip().lower() == "read" else "write"


def list_samba_users(config: SambaConfig) -> tuple[list[dict[str, Any]], str | None]:
    result = _admin(config, "list-json")
    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "list failed").strip()
    raw = (result.stdout or "").strip()
    if not raw:
        return [], None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], "Invalid response from Samba admin"
    if not isinstance(data, list):
        return [], "Invalid response from Samba admin"
    users: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        name = str(row.get("username") or "").strip()
        if not name:
            continue
        access = _parse_access(str(row.get("access") or "write"))
        users.append(
            {
                "username": name,
                "access": access,
                "access_label": "Read-only" if access == "read" else "Read & write",
            }
        )
    return users, None


def add_samba_user(
    config: SambaConfig,
    username: str,
    password: str,
    *,
    access: SambaAccess = "write",
) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username (lowercase letters, digits, _ - only)"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if access not in ("read", "write"):
        return False, "Access must be read or write"
    result = _admin(config, "add", user, password, access)
    if result.returncode == 0:
        label = "read-only" if access == "read" else "read & write"
        return True, f"Added Samba user {user} ({label})"
    return False, (result.stderr or result.stdout or "add failed").strip()


def remove_samba_user(config: SambaConfig, username: str) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username"
    result = _admin(config, "remove", user)
    if result.returncode == 0:
        return True, f"Removed Samba user {user}"
    return False, (result.stderr or result.stdout or "remove failed").strip()


def set_samba_user_password(
    config: SambaConfig,
    username: str,
    password: str,
) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    result = _admin(config, "set-password", user, password)
    if result.returncode == 0:
        return True, f"Password updated for {user}"
    return False, (result.stderr or result.stdout or "set-password failed").strip()


def set_samba_user_access(
    config: SambaConfig,
    username: str,
    access: SambaAccess,
) -> tuple[bool, str]:
    user = username.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", user):
        return False, "Invalid username"
    if access not in ("read", "write"):
        return False, "Access must be read or write"
    result = _admin(config, "set-access", user, access)
    if result.returncode == 0:
        label = "read-only" if access == "read" else "read & write"
        return True, f"{user} is now {label} on the share"
    return False, (result.stderr or result.stdout or "set-access failed").strip()


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
        "connect_url": smb_connect_url(config.unc_path),
        "users": users,
        "users_error": err,
    }
