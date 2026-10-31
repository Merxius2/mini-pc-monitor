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
            sync = re.search(r"\[([UU]+|[_U]+|U_]+)\]", line)
            if sync:
                current["sync"] = sync.group(1)
            blocks = re.search(r"(\d+)\s+blocks", line)
            if blocks:
                current["blocks"] = int(blocks.group(1))
    if current:
        arrays.append(current)
    return {"arrays": arrays, "raw": text.strip()}


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
    usage: dict[str, Any] = {
        "mount": mount,
        "mounted": mounted,
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

    overall = "ok"
    if not mounted:
        overall = "warn"
    elif target and target.get("sync") and "U" in target.get("sync", "") and "_" in target.get("sync", ""):
        overall = "amber"
    elif target and target.get("state") != "active":
        overall = "warn"

    return {
        "overall": overall,
        "mount": usage,
        "array": target,
        "arrays": mdstat["arrays"],
        "mdadm_detail": detail_text.strip() or None,
    }
