"""RAID array and mount status for /mnt/storage."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _human_bytes(n: int) -> str:
    if n < 0:
        return "—"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _mount_options(mount: str) -> str | None:
    mounts_path = Path("/proc/mounts")
    if not mounts_path.is_file():
        return None
    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == mount:
            return parts[3]
    return None


def _is_read_only_mount(options: str | None) -> bool:
    if not options:
        return False
    if "emergency_ro" in options:
        return True
    opts = options.split(",")
    return "ro" in opts and "rw" not in opts


def _parse_mdstat(text: str) -> dict[str, Any]:
    arrays: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        m = re.match(r"^(md\d+)\s*:\s*(\w+)\s+(\w+)\s+(.+)$", line.strip())
        if m:
            if current:
                arrays.append(current)
            device, state, level, rest = m.groups()
            members = re.findall(r"(\w+)\[\d+\]", rest)
            current = {
                "device": f"/dev/{device}",
                "name": device,
                "state": state,
                "level": level,
                "members": members,
                "detail": rest.strip(),
            }
            continue
        if current and line.strip():
            current["extra"] = (current.get("extra") or "") + " " + line.strip()
            sync = re.search(r"\[(\d+/\d+)\]\s*\[([U_]+)\]", line)
            if sync:
                current["raid_devices"] = sync.group(1)
                current["sync"] = sync.group(2)
            else:
                sync = re.search(r"\[([UU]+|[_U]+|U_]+)\]", line)
                if sync:
                    current["sync"] = sync.group(1)
            blocks = re.search(r"(\d+)\s+blocks", line)
            if blocks:
                current["blocks"] = int(blocks.group(1))
    if current:
        arrays.append(current)
    return {"arrays": arrays, "raw": text.strip()}


def _health_level_for_disk(state: str, device: str | None) -> str:
    text = state.lower()
    if not device or any(word in text for word in ("removed", "faulty", "failed", "missing")):
        return "warn"
    if "active sync" in text:
        return "ok"
    if any(word in text for word in ("spare", "rebuild", "resync", "recover")):
        return "amber"
    if text.startswith("active"):
        return "ok"
    return "amber"


def _parse_mdadm_disks(detail_text: str) -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    in_table = False
    for line in detail_text.splitlines():
        if "RaidDevice" in line and "Number" in line:
            in_table = True
            continue
        if not in_table or not line.strip():
            continue
        m = re.match(r"^\s*\d+\s+\d+\s+\d+\s+\d+\s+(.+)$", line)
        if not m:
            continue
        rest = m.group(1).strip()
        parts = rest.split()
        device = parts[-1] if parts and parts[-1].startswith("/dev/") else None
        state = rest if device is None else " ".join(parts[:-1]).strip()
        level = _health_level_for_disk(state, device)
        disks.append(
            {
                "device": device or "—",
                "state": state,
                "level": level,
                "dot": _level_to_dot(level),
            }
        )
    return disks


def _level_to_dot(level: str) -> str:
    return {"ok": "bull", "amber": "amber", "warn": "bear"}.get(level, "neutral")


def _array_health(
    *,
    overall: str,
    degraded: bool,
    read_only: bool,
    mounted: bool,
    target: dict[str, Any] | None,
    detail_text: str,
) -> dict[str, str]:
    failed = 0
    m = re.search(r"Failed Devices\s*:\s*(\d+)", detail_text)
    if m:
        failed = int(m.group(1))
    if not mounted or read_only or failed > 0:
        level = "warn"
        label = "critical"
    elif degraded or (target and target.get("state") in ("broken", "inactive")):
        level = "amber"
        label = "degraded"
    elif overall == "ok":
        level = "ok"
        label = "healthy"
    else:
        level = "amber"
        label = "check"
    return {"level": level, "dot": _level_to_dot(level), "label": label}


def _array_degraded(target: dict[str, Any] | None, detail_text: str) -> bool:
    if not target:
        return True
    if target.get("state") in ("broken", "inactive"):
        return True
    sync = target.get("sync") or ""
    if "_" in sync:
        return True
    if re.search(r"degraded|failed|broken", detail_text, re.I):
        return True
    m = re.search(r"Active Devices\s*:\s*(\d+)", detail_text)
    n = re.search(r"Raid Devices\s*:\s*(\d+)", detail_text)
    if m and n and int(m.group(1)) < int(n.group(1)):
        return True
    return False


def _build_alerts(
    *,
    mounted: bool,
    read_only: bool,
    degraded: bool,
    target: dict[str, Any] | None,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if not mounted:
        alerts.append(
            {
                "level": "warn",
                "title": "Storage not mounted",
                "detail": "/mnt/storage is not mounted — torrents and Samba will fail.",
            }
        )
    if read_only:
        alerts.append(
            {
                "level": "warn",
                "title": "Storage is read-only",
                "detail": "The RAID filesystem was remounted read-only (often after a disk error). "
                "Do not rely on torrents until the array is healthy and the volume is read-write again. "
                "Check RAID storage page and consider fsck after fixing mirrors.",
            }
        )
    if degraded:
        members = ", ".join(target.get("members", [])) if target else "—"
        sync = target.get("sync") if target else "—"
        alerts.append(
            {
                "level": "amber",
                "title": "RAID mirror degraded or broken",
                "detail": f"md0 is not fully redundant (state: {target.get('state') if target else 'unknown'}, "
                f"sync: [{sync}], members: {members}). Replace failed disks and rebuild when possible.",
            }
        )
    return alerts


def get_raid_status(*, md_device: str = "/dev/md0", mount: str = "/mnt/storage") -> dict[str, Any]:
    mdstat_path = Path("/proc/mdstat")
    mdstat = _parse_mdstat(mdstat_path.read_text(encoding="utf-8")) if mdstat_path.is_file() else {"arrays": [], "raw": ""}

    target = next((a for a in mdstat["arrays"] if a["device"] == md_device), None)
    detail_text = ""
    detail = _run(["mdadm", "--detail", md_device])
    if detail.returncode == 0:
        detail_text = detail.stdout
        m = re.search(r"State\s*:\s*(.+)", detail_text)
        if m and target:
            target["mdadm_state"] = m.group(1).strip()
        m = re.search(r"UUID\s*:\s*(\S+)", detail_text)
        if m and target:
            target["uuid"] = m.group(1)

    mounted = Path(mount).is_mount()
    mount_opts = _mount_options(mount) if mounted else None
    read_only = _is_read_only_mount(mount_opts)
    degraded = _array_degraded(target, detail_text)

    usage: dict[str, Any] = {
        "mount": mount,
        "mounted": mounted,
        "read_only": read_only,
        "mount_options": mount_opts,
        "total_bytes": 0,
        "used_bytes": 0,
        "free_bytes": 0,
        "percent": 0,
        "total_human": "—",
        "used_human": "—",
        "free_human": "—",
    }
    if mounted:
        du = shutil.disk_usage(mount)
        usage.update(
            {
                "total_bytes": du.total,
                "used_bytes": du.used,
                "free_bytes": du.free,
                "percent": round(100 * du.used / du.total, 1) if du.total else 0,
                "total_human": _human_bytes(du.total),
                "used_human": _human_bytes(du.used),
                "free_human": _human_bytes(du.free),
            }
        )

    alerts = _build_alerts(mounted=mounted, read_only=read_only, degraded=degraded, target=target)

    overall = "ok"
    if not mounted or read_only:
        overall = "warn"
    elif degraded:
        overall = "amber"

    disks = _parse_mdadm_disks(detail_text) if detail_text else []
    if not disks and target:
        sync = target.get("sync") or ""
        for member in target.get("members") or []:
            level = "ok" if sync and "_" not in sync else "amber"
            if target.get("state") == "broken":
                level = "warn"
            disks.append(
                {
                    "device": f"/dev/{member}",
                    "state": target.get("state", "unknown"),
                    "level": level,
                    "dot": _level_to_dot(level),
                }
            )

    array_health = _array_health(
        overall=overall,
        degraded=degraded,
        read_only=read_only,
        mounted=mounted,
        target=target,
        detail_text=detail_text,
    )

    return {
        "overall": overall,
        "mount": usage,
        "array": target,
        "arrays": mdstat["arrays"],
        "mdadm_detail": detail_text.strip() or None,
        "read_only": read_only,
        "degraded": degraded,
        "alerts": alerts,
        "has_alerts": bool(alerts),
        "array_health": array_health,
        "disks": disks,
    }
