"""Transmission RPC client and torrent listing."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.config_loader import TransmissionConfig


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _read_rpc_password(config: TransmissionConfig) -> str:
    path = Path(config.rpc_password_file)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return config.rpc_password or ""


class TransmissionClient:
    def __init__(self, config: TransmissionConfig) -> None:
        self.config = config
        self._session_id: str | None = None
        self._password = _read_rpc_password(config)

    def _request(self, method: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"method": method, "arguments": arguments or {}}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id

        password_mgr = None
        if self.config.rpc_username and self._password:
            password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, self.config.rpc_url, self.config.rpc_username, self._password)

        opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(password_mgr))
        req = urllib.request.Request(self.config.rpc_url, data=body, headers=headers, method="POST")
        try:
            with opener.open(req, timeout=8) as resp:
                self._session_id = resp.headers.get("X-Transmission-Session-Id") or self._session_id
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                self._session_id = exc.headers.get("X-Transmission-Session-Id")
                return self._request(method, arguments)
            raise
        if payload.get("result") != "success":
            raise RuntimeError(payload.get("result", "RPC error"))
        return payload

    def list_torrents(self) -> list[dict[str, Any]]:
        data = self._request(
            "torrent-get",
            {
                "fields": [
                    "id",
                    "name",
                    "status",
                    "percentDone",
                    "rateDownload",
                    "rateUpload",
                    "eta",
                    "totalSize",
                    "downloadedEver",
                    "uploadedEver",
                    "errorString",
                    "isFinished",
                ]
            },
        )
        rows: list[dict[str, Any]] = []
        for t in data.get("arguments", {}).get("torrents", []):
            pct = round(float(t.get("percentDone", 0)) * 100, 1)
            status_code = int(t.get("status", 0))
            rows.append(
                {
                    "id": t["id"],
                    "name": t.get("name") or "—",
                    "percent": pct,
                    "status_code": status_code,
                    "status": _status_label(status_code),
                    "eta": _format_eta(int(t.get("eta", -1))),
                    "download_rate": _format_rate(int(t.get("rateDownload", 0))),
                    "upload_rate": _format_rate(int(t.get("rateUpload", 0))),
                    "size_human": _human_bytes(int(t.get("totalSize", 0))),
                    "error": t.get("errorString") or "",
                }
            )
        rows.sort(key=lambda r: (-r["percent"], r["name"].lower()))
        return rows

    def add_torrent_bytes(self, data: bytes, download_dir: str | None = None) -> None:
        args: dict[str, Any] = {"metainfo": base64.standard_b64encode(data).decode("ascii")}
        if download_dir:
            args["download-dir"] = download_dir
        self._request("torrent-add", args)

    def add_torrent_magnet(self, magnet: str) -> None:
        self._request("torrent-add", {"filename": magnet.strip()})

    def remove_torrent(self, torrent_id: int, *, delete_data: bool = False) -> None:
        self._request("torrent-remove", {"ids": [torrent_id], "delete-local-data": delete_data})

    def start_torrent(self, torrent_id: int) -> None:
        self._request("torrent-start", {"ids": [torrent_id]})

    def stop_torrent(self, torrent_id: int) -> None:
        self._request("torrent-stop", {"ids": [torrent_id]})


def _status_label(code: int) -> str:
    return {
        0: "stopped",
        1: "check pending",
        2: "checking",
        3: "download pending",
        4: "downloading",
        5: "seed pending",
        6: "seeding",
    }.get(code, f"status {code}")


def _format_eta(seconds: int) -> str:
    if seconds < 0:
        return "—"
    if seconds == 0:
        return "0m"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {sec}s"


def _format_rate(bps: int) -> str:
    if bps <= 0:
        return "—"
    if bps < 1024:
        return f"{bps} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / (1024 * 1024):.1f} MB/s"


def _human_bytes(n: int) -> str:
    if n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{n} {unit}"
            return f"{n / 1024:.1f} {unit}"
        n //= 1024
    return str(n)


def get_transmission_status(config: TransmissionConfig) -> dict[str, Any]:
    unit = config.systemd_unit
    active = _run(["systemctl", "is-active", unit]).stdout.strip() or "unknown"
    torrents: list[dict[str, Any]] = []
    rpc_ok = False
    rpc_error: str | None = None
    if active == "active":
        try:
            client = TransmissionClient(config)
            torrents = client.list_torrents()
            rpc_ok = True
        except Exception as exc:  # noqa: BLE001 — surface to UI
            rpc_error = str(exc)
    overall = "ok" if active == "active" and rpc_ok else ("amber" if active == "active" else "warn")
    return {
        "unit": unit,
        "active": active,
        "overall": overall,
        "rpc_ok": rpc_ok,
        "rpc_error": rpc_error,
        "torrents": torrents,
        "download_dir": config.download_dir,
        "watch_dir": config.watch_dir,
    }


def transmission_client(config: TransmissionConfig) -> TransmissionClient:
    return TransmissionClient(config)
