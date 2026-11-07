"""Marstek Venus local API (UDP JSON-RPC on port 30000)."""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config_loader import MarstekConfig

_UDP_LOCK = threading.Lock()

_STATUS_METHODS = (
    "Wifi.GetStatus",
    "Bat.GetStatus",
    "ES.GetStatus",
    "EM.GetStatus",
    "ES.GetMode",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_ct_state(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class MarstekStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if not self.path.is_file():
            self._data = {"selected": [], "discovered": [], "ct_lost_since": {}}
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {"selected": [], "discovered": [], "ct_lost_since": {}}
        self._data.setdefault("selected", [])
        self._data.setdefault("discovered", [])
        self._data.setdefault("ct_lost_since", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @property
    def selected(self) -> list[dict[str, Any]]:
        return list(self._data.get("selected") or [])

    @property
    def discovered(self) -> list[dict[str, Any]]:
        return list(self._data.get("discovered") or [])

    def set_discovered(self, devices: list[dict[str, Any]]) -> None:
        merged: dict[str, dict[str, Any]] = {}
        for row in self.discovered + devices:
            key = _device_key(row)
            if key:
                merged[key] = {**merged.get(key, {}), **row}
        self._data["discovered"] = sorted(merged.values(), key=lambda d: d.get("ip") or "")
        self.save()

    def toggle_selected(self, device: dict[str, Any], *, on: bool) -> None:
        key = _device_key(device)
        if not key:
            return
        selected = [d for d in self.selected if _device_key(d) != key]
        if on:
            label = device.get("label") or device.get("src") or device.get("ip") or key
            selected.append(
                {
                    "id": key,
                    "ip": device.get("ip"),
                    "src": device.get("src"),
                    "device": device.get("device"),
                    "label": label,
                }
            )
        self._data["selected"] = selected
        self.save()

    def update_label(self, device_id: str, label: str) -> None:
        for row in self._data["selected"]:
            if row.get("id") == device_id:
                row["label"] = label.strip() or row.get("label") or device_id
        self.save()

    def ct_lost_since(self) -> dict[str, str]:
        raw = self._data.get("ct_lost_since") or {}
        return {str(k): str(v) for k, v in raw.items()}

    def set_ct_lost_since(self, mapping: dict[str, str]) -> None:
        self._data["ct_lost_since"] = dict(mapping)
        self.save()


def _device_key(device: dict[str, Any]) -> str:
    return str(device.get("id") or device.get("ip") or device.get("src") or device.get("ble_mac") or "")


def _make_socket(config: MarstekConfig) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(config.request_timeout)
    if config.bind_port:
        sock.bind((config.bind_host, config.bind_port))
    return sock


def marstek_rpc(
    config: MarstekConfig,
    host: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    req_id: int = 1,
    timeout: float | None = None,
) -> dict[str, Any]:
    payload = {"id": req_id, "method": method, "params": params if params is not None else {"id": 0}}
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    addr = (host, config.udp_port)
    deadline = time.monotonic() + (timeout if timeout is not None else config.request_timeout)

    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            sock.sendto(data, addr)
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                sock.settimeout(remaining)
                try:
                    raw, _peer = sock.recvfrom(65535)
                except TimeoutError:
                    break
                except OSError:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(message, dict) and (
                    message.get("method") is None or message.get("id") == req_id
                ):
                    return message
        finally:
            sock.close()
    return {"error": {"message": "timeout", "code": -32000}}


def _device_from_message(message: dict[str, Any], fallback_ip: str | None = None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    if message.get("error") and not message.get("result"):
        src = message.get("src")
        if src and fallback_ip:
            return {"src": src, "ip": fallback_ip, "id": src}
        return None
    result = message.get("result")
    if not isinstance(result, dict):
        src = message.get("src")
        if src:
            return {"src": src, "ip": result.get("ip") if isinstance(result, dict) else fallback_ip, "id": src}
        return None
    ip = result.get("ip") or result.get("sta_ip") or fallback_ip
    src = message.get("src") or ""
    device = {
        "ip": ip,
        "src": src,
        "device": result.get("device"),
        "ble_mac": result.get("ble_mac"),
        "wifi_mac": result.get("wifi_mac"),
        "wifi_name": result.get("wifi_name"),
        "ver": result.get("ver"),
        "id": _device_key({"ip": ip, "src": src, "ble_mac": result.get("ble_mac")}),
    }
    return device if device.get("id") else None


def discover_marstek_devices(config: MarstekConfig) -> list[dict[str, Any]]:
    payload = {"id": 0, "method": "Marstek.GetDevice", "params": {"ble_mac": "0"}}
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    found: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + config.discover_timeout

    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for bcast in config.broadcast_hosts:
                try:
                    sock.sendto(data, (bcast, config.udp_port))
                except OSError:
                    continue
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                sock.settimeout(remaining)
                try:
                    raw, peer = sock.recvfrom(65535)
                except TimeoutError:
                    break
                except OSError:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                device = _device_from_message(message, fallback_ip=peer[0])
                if device and device.get("id"):
                    found[device["id"]] = {**device, "ip": device.get("ip") or peer[0]}
        finally:
            sock.close()

    for host in config.manual_hosts:
        message = marstek_rpc(config, host, "Marstek.GetDevice", params={"ble_mac": "0"}, req_id=42)
        device = _device_from_message(message, fallback_ip=host)
        if device and device.get("id"):
            found[device["id"]] = {**device, "ip": device.get("ip") or host}

    return sorted(found.values(), key=lambda d: (d.get("label") or d.get("src") or d.get("ip") or ""))


def poll_marstek_device(config: MarstekConfig, ip: str) -> dict[str, Any]:
    status: dict[str, Any] = {
        "ip": ip,
        "online": False,
        "polled_at": _utc_now_iso(),
        "methods": {},
        "error": None,
    }
    device_info = marstek_rpc(config, ip, "Marstek.GetDevice", params={"ble_mac": "0"}, req_id=10)
    device = _device_from_message(device_info, fallback_ip=ip)
    if device:
        status.update({k: device.get(k) for k in ("src", "device", "ble_mac", "wifi_name") if device.get(k)})
        status["online"] = True
    for idx, method in enumerate(_STATUS_METHODS, start=20):
        reply = marstek_rpc(config, ip, method, req_id=idx)
        if reply.get("result") is not None:
            status["online"] = True
            status["methods"][method] = reply["result"]
        elif reply.get("error") and not status["error"]:
            status["error"] = reply["error"].get("message") or str(reply["error"])

    em = status["methods"].get("EM.GetStatus") or {}
    mode = status["methods"].get("ES.GetMode") or {}
    bat = status["methods"].get("Bat.GetStatus") or {}
    es = status["methods"].get("ES.GetStatus") or {}
    wifi = status["methods"].get("Wifi.GetStatus") or {}

    ct_state = _parse_ct_state(em.get("ct_state"))
    if ct_state is None:
        ct_state = _parse_ct_state(mode.get("ct_state"))

    status["display"] = {
        "soc": _first_number(bat.get("soc"), es.get("bat_soc")),
        "bat_power": es.get("bat_power"),
        "bat_temp": bat.get("bat_temp"),
        "bat_capacity_wh": bat.get("bat_capacity"),
        "rated_capacity_wh": bat.get("rated_capacity"),
        "pv_power": es.get("pv_power"),
        "ongrid_power": es.get("ongrid_power"),
        "offgrid_power": es.get("offgrid_power"),
        "total_power": em.get("total_power") or mode.get("total_power"),
        "mode": mode.get("mode"),
        "ct_state": ct_state,
        "ct_connected": ct_state == 1,
        "wifi_rssi": wifi.get("rssi"),
        "ssid": wifi.get("ssid"),
    }
    return status


def _first_number(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        return value
    return None


def get_store(config: MarstekConfig) -> MarstekStore:
    return MarstekStore(Path(config.data_file))


def update_ct_alerts(
    config: MarstekConfig,
    store: MarstekStore,
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    threshold = max(60, int(config.ct_alert_after_seconds))
    lost_map = dict(store.ct_lost_since())

    by_ip = {str(s.get("ip")): s for s in statuses}
    for selected in store.selected:
        dev_id = str(selected.get("id") or "")
        ip = str(selected.get("ip") or "")
        if not dev_id or not ip:
            continue
        label = selected.get("label") or selected.get("src") or ip
        status = by_ip.get(ip)
        if not status or not status.get("online"):
            continue
        display = status.get("display") or {}
        ct_state = display.get("ct_state")
        if ct_state == 1:
            lost_map.pop(dev_id, None)
            continue
        if ct_state not in (0, None):
            continue
        since_raw = lost_map.get(dev_id)
        if not since_raw:
            lost_map[dev_id] = _utc_now_iso()
            continue
        try:
            since = datetime.fromisoformat(since_raw.replace("Z", "+00:00"))
        except ValueError:
            lost_map[dev_id] = _utc_now_iso()
            continue
        elapsed = (now - since).total_seconds()
        if elapsed >= threshold:
            alerts.append(
                {
                    "device_id": dev_id,
                    "label": label,
                    "ip": ip,
                    "lost_minutes": int(elapsed // 60),
                    "message": f"CT link lost on {label} for {int(elapsed // 60)} min",
                }
            )

    store.set_ct_lost_since(lost_map)
    return alerts


def get_marstek_dashboard(config: MarstekConfig) -> dict[str, Any]:
    if not config.enabled:
        return {"enabled": False}
    store = get_store(config)
    statuses = [poll_marstek_device(config, row["ip"]) for row in store.selected if row.get("ip")]
    alerts = update_ct_alerts(config, store, statuses)
    return {
        "enabled": True,
        "config": config,
        "selected": store.selected,
        "selected_ids": {str(s.get("id") or "") for s in store.selected if s.get("id")},
        "discovered": store.discovered,
        "devices": statuses,
        "alerts": alerts,
        "has_ct_alerts": bool(alerts),
    }
