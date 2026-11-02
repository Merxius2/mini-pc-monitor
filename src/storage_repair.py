"""Detect degraded RAID and run minipc-ensure-storage.sh (by-id re-assemble)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from src.config_loader import StorageConfig
from src.storage import get_raid_status


def raid_needs_repair(raid: dict[str, Any]) -> bool:
    if raid.get("degraded"):
        return True
    if raid.get("read_only"):
        return True
    mount = raid.get("mount") or {}
    if not mount.get("mounted"):
        return True
    target = raid.get("array")
    if target and target.get("state") in ("broken", "inactive"):
        return True
    sync = (target or {}).get("sync") or ""
    if sync and "_" in sync:
        return True
    return False


def _cooldown_path(config: StorageConfig) -> Path:
    return Path(config.repair_cooldown_file)


def _cooldown_active(config: StorageConfig, *, now: float | None = None) -> bool:
    path = _cooldown_path(config)
    if not path.is_file():
        return False
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    now = now if now is not None else time.time()
    return (now - last) < max(60, int(config.repair_cooldown_seconds))


def _mark_repair_run(config: StorageConfig, *, now: float | None = None) -> None:
    path = _cooldown_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(now if now is not None else time.time()), encoding="utf-8")


def repair_raid(
    config: StorageConfig,
    *,
    force: bool = False,
    now: float | None = None,
) -> tuple[bool, str, bool]:
    """Run ensure-storage script. Returns (ok, message, skipped_due_to_cooldown)."""
    if not config.auto_repair and not force:
        return False, "RAID auto-repair disabled in config", False
    script = Path(config.ensure_script)
    if not script.is_file():
        return False, f"Repair script not found: {script}", False
    if not force and _cooldown_active(config, now=now):
        return False, "RAID repair skipped (cooldown — try again later or use Repair now)", True

    result = subprocess.run(
        ["sudo", "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=max(120, int(config.repair_timeout_seconds)),
    )
    _mark_repair_run(config, now=now)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "ensure-storage failed").strip()
        return False, err[:500], False
    return True, "RAID repair script finished", False


def get_raid_status_with_repair(
    config: StorageConfig,
    *,
    force_repair: bool = False,
) -> dict[str, Any]:
    raid = get_raid_status(md_device=config.md_device, mount=config.mount)
    repair_info: dict[str, Any] | None = None

    if config.enabled and (force_repair or (config.auto_repair and raid_needs_repair(raid))):
        ok, message, skipped = repair_raid(config, force=force_repair)
        repair_info = {
            "attempted": not skipped,
            "ok": ok,
            "message": message,
            "skipped_cooldown": skipped,
        }
        if ok and not skipped:
            raid = get_raid_status(md_device=config.md_device, mount=config.mount)
            repair_info["healthy_after"] = not raid_needs_repair(raid)

    if repair_info:
        raid["repair"] = repair_info
    return raid
