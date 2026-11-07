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
_POLLER_LOCK = threading.Lock()
_POLLER_STARTED = False

_STATUS_CACHE: dict[str, dict[str, Any]] = {}
_LINK_RTT: dict[str, tuple[float, float]] = {}  # host -> (monotonic, rtt_ms)

# Wi‑Fi firmware rate-limits back-to-back queries (~3.7 s). ES.GetStatus is flaky on some Venus E fw.
_POLL_METHODS = (
    "Marstek.GetDevice",
    "ES.GetMode",
    "Bat.GetStatus",
    "EM.GetStatus",
    "Wifi.GetStatus",
    "ES.GetStatus",
)


def normalize_ip(ip: str | None) -> str:
    """Marstek firmware may report zero-padded IPv4 octets (e.g. 192.168.01.27)."""
    if not ip or not isinstance(ip, str):
        return str(ip or "")
    parts = ip.strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return ip.strip()
    return ".".join(str(int(p)) for p in parts)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_ct_state(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_number(raw: Any) -> int | float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class MarstekStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        self.load()

    def _normalize_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            fixed = dict(row)
            ip = normalize_ip(fixed.get("ip"))
            if ip:
                fixed["ip"] = ip
                if fixed.get("id") == row.get("ip") or fixed.get("id") == ip:
                    fixed["id"] = ip
            out.append(fixed)
        return out

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
        selected = self._normalize_rows(list(self._data.get("selected") or []))
        discovered = self._normalize_rows(list(self._data.get("discovered") or []))
        if selected != self._data.get("selected") or discovered != self._data.get("discovered"):
            self._data["selected"] = selected
            self._data["discovered"] = discovered
            self.save()

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
            ip = normalize_ip(device.get("ip"))
            label = device.get("label") or device.get("src") or ip or key
            selected.append(
                {
                    "id": key if key != device.get("ip") else ip or key,
                    "ip": ip or device.get("ip"),
                    "src": device.get("src"),
                    "device": device.get("device"),
                    "label": label,
                }
            )
        self._data["selected"] = self._normalize_rows(selected)
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
    ip = normalize_ip(device.get("ip"))
    if ip:
        return ip
    return str(device.get("id") or device.get("src") or device.get("ble_mac") or "")


def _make_socket(config: MarstekConfig) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if config.bind_port:
        sock.bind((config.bind_host, config.bind_port))
    return sock


def _inter_request_delay(config: MarstekConfig, host: str) -> float:
    entry = _LINK_RTT.get(host)
    if entry and time.monotonic() - entry[0] < 3600:
        rtt = entry[1]
    else:
        rtt = _probe_link_rtt(config, host)
    if rtt is None:
        return config.request_delay
    if rtt >= config.wifi_rtt_threshold_ms:
        return config.request_delay
    return config.request_delay_fast


def _probe_link_rtt(config: MarstekConfig, host: str) -> float | None:
    host = normalize_ip(host)
    payload = {"id": 9001, "method": "Marstek.GetDevice", "params": {"ble_mac": "0"}}
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    t0 = time.monotonic()
    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            sock.sendto(data, (host, config.udp_port))
            deadline = t0 + min(4.0, config.request_timeout)
            sock.settimeout(0.25)
            while time.monotonic() < deadline:
                try:
                    raw, peer = sock.recvfrom(65535)
                except TimeoutError:
                    continue
                if peer[0] != host:
                    continue
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if message.get("id") == 9001 or message.get("result"):
                    rtt_ms = (time.monotonic() - t0) * 1000
                    _LINK_RTT[host] = (time.monotonic(), rtt_ms)
                    return rtt_ms
        except OSError:
            return None
        finally:
            sock.close()
    return None


def _rpc_on_socket(
    sock: socket.socket,
    config: MarstekConfig,
    host: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    req_id: int,
) -> dict[str, Any]:
    host = normalize_ip(host)
    if method == "Marstek.GetDevice":
        payload_params: dict[str, Any] = params if params is not None else {"ble_mac": "0"}
    else:
        payload_params = params if params is not None else {"id": 0}
    payload = {"id": req_id, "method": method, "params": payload_params}
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    deadline = time.monotonic() + max(4.0, config.request_timeout)

    try:
        sock.sendto(data, (host, config.udp_port))
    except OSError as exc:
        return {"error": {"message": str(exc), "code": -32000}}

    sock.settimeout(0.25)
    while time.monotonic() < deadline:
        try:
            raw, peer = sock.recvfrom(65535)
        except TimeoutError:
            continue
        except OSError:
            break
        if peer[0] != host:
            continue
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(message, dict):
            continue
        if message.get("id") != req_id:
            continue
        return message
    return {"error": {"message": "timeout", "code": -32000}}


def marstek_rpc(
    config: MarstekConfig,
    host: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    req_id: int = 1,
    timeout: float | None = None,
) -> dict[str, Any]:
    _ = timeout
    host = normalize_ip(host)
    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            return _rpc_on_socket(sock, config, host, method, params=params, req_id=req_id)
        finally:
            sock.close()


def _device_from_message(message: dict[str, Any], fallback_ip: str | None = None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    if message.get("error") and not message.get("result"):
        src = message.get("src")
        if src and fallback_ip:
            ip = normalize_ip(fallback_ip)
            return {"src": src, "ip": ip, "id": ip}
        return None
    result = message.get("result")
    if not isinstance(result, dict):
        src = message.get("src")
        if src:
            ip = normalize_ip(fallback_ip) if fallback_ip else None
            return {"src": src, "ip": ip, "id": ip or src}
        return None
    ip = normalize_ip(result.get("ip") or result.get("sta_ip") or fallback_ip)
    src = message.get("src") or ""
    device = {
        "ip": ip,
        "src": src,
        "device": result.get("device"),
        "ble_mac": result.get("ble_mac"),
        "wifi_mac": result.get("wifi_mac"),
        "wifi_name": result.get("wifi_name"),
        "ver": result.get("ver"),
        "id": ip or _device_key({"ip": ip, "src": src, "ble_mac": result.get("ble_mac")}),
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
            sock.settimeout(0.25)
            while time.monotonic() < deadline:
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
                    ip = normalize_ip(device.get("ip") or peer[0])
                    found[device["id"]] = {**device, "ip": ip, "id": ip}
        finally:
            sock.close()

    for host in config.manual_hosts:
        message = marstek_rpc(
            config,
            host,
            "Marstek.GetDevice",
            params={"ble_mac": "0"},
            req_id=42,
        )
        device = _device_from_message(message, fallback_ip=host)
        if device and device.get("id"):
            ip = normalize_ip(device.get("ip") or host)
            found[device["id"]] = {**device, "ip": ip, "id": ip}

    return sorted(found.values(), key=lambda d: (d.get("label") or d.get("src") or d.get("ip") or ""))


def _scale_energy_wh(raw: Any, factor: float) -> float | None:
    value = _parse_number(raw)
    if value is None:
        return None
    return float(value) * factor


def _build_display(methods: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    em = methods.get("EM.GetStatus") or {}
    mode = methods.get("ES.GetMode") or {}
    bat = methods.get("Bat.GetStatus") or {}
    es = methods.get("ES.GetStatus") or {}
    wifi = methods.get("Wifi.GetStatus") or {}

    ct_state = _parse_ct_state(em.get("ct_state"))
    if ct_state is None:
        ct_state = _parse_ct_state(mode.get("ct_state"))

    soc = _parse_number(bat.get("soc"))
    if soc is None:
        soc = _parse_number(mode.get("bat_soc"))
    if soc is None:
        soc = _parse_number(es.get("bat_soc"))

    bat_cap = _parse_number(bat.get("bat_capacity"))
    if bat_cap is None:
        bat_cap = _parse_number(es.get("bat_cap"))
    if bat_cap is None:
        bat_cap = _parse_number(mode.get("bat_cap"))

    rated = _parse_number(bat.get("rated_capacity"))
    if rated is None:
        rated = _parse_number(meta.get("rated_capacity_wh"))

    return {
        "soc": soc,
        "bat_power": _first_number(es.get("bat_power"), mode.get("bat_power")),
        "bat_temp": bat.get("bat_temp"),
        "bat_capacity_wh": bat_cap,
        "rated_capacity_wh": rated,
        "pv_power": _first_number(es.get("pv_power"), mode.get("pv_power")),
        "ongrid_power": _first_number(es.get("ongrid_power"), mode.get("ongrid_power")),
        "offgrid_power": _first_number(es.get("offgrid_power"), mode.get("offgrid_power")),
        "total_power": _first_number(em.get("total_power"), mode.get("total_power")),
        "a_power": _first_number(em.get("a_power"), mode.get("a_power")),
        "b_power": _first_number(em.get("b_power"), mode.get("b_power")),
        "c_power": _first_number(em.get("c_power"), mode.get("c_power")),
        "mode": mode.get("mode"),
        "firmware": meta.get("ver"),
        "ct_state": ct_state,
        "ct_connected": ct_state == 1,
        "wifi_rssi": wifi.get("rssi"),
        "ssid": wifi.get("ssid") or meta.get("wifi_name"),
        "total_pv_wh": _scale_energy_wh(es.get("total_pv_energy"), 10.0),
        "grid_export_wh": _parse_number(es.get("total_grid_output_energy")),
        "grid_import_wh": _parse_number(es.get("total_grid_input_energy")),
        "ct_input_wh": _scale_energy_wh(em.get("input_energy"), 0.1),
        "ct_output_wh": _scale_energy_wh(em.get("output_energy"), 0.1),
    }


def poll_marstek_device(config: MarstekConfig, ip: str) -> dict[str, Any]:
    ip = normalize_ip(ip)
    delay = _inter_request_delay(config, ip)
    status: dict[str, Any] = {
        "ip": ip,
        "online": False,
        "polled_at": _utc_now_iso(),
        "methods": {},
        "errors": {},
        "error": None,
    }
    meta: dict[str, Any] = {}

    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            for idx, method in enumerate(_POLL_METHODS, start=1):
                if idx > 1 and delay > 0:
                    time.sleep(delay)
                reply = _rpc_on_socket(sock, config, ip, method, req_id=1000 + idx)
                if reply.get("result") is not None:
                    status["online"] = True
                    result = reply["result"]
                    status["methods"][method] = result
                    if method == "Marstek.GetDevice" and isinstance(result, dict):
                        meta["ver"] = result.get("ver")
                        meta["wifi_name"] = result.get("wifi_name")
                    if reply.get("src"):
                        status["src"] = reply["src"]
                    if isinstance(result, dict) and result.get("device"):
                        status["device"] = result.get("device")
                elif reply.get("error"):
                    err = reply["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    status["errors"][method] = msg
        finally:
            sock.close()

    if status["online"] and "Bat.GetStatus" not in status["methods"]:
        time.sleep(delay or config.request_delay)
        with _UDP_LOCK:
            sock = _make_socket(config)
            try:
                reply = _rpc_on_socket(sock, config, ip, "Bat.GetStatus", req_id=1999)
                if reply.get("result") is not None:
                    status["methods"]["Bat.GetStatus"] = reply["result"]
            finally:
                sock.close()

    if status["methods"].get("Marstek.GetDevice"):
        device = _device_from_message(
            {"result": status["methods"]["Marstek.GetDevice"], "src": status.get("src")},
            fallback_ip=ip,
        )
        if device:
            status.update({k: device.get(k) for k in ("src", "device", "ble_mac", "wifi_name", "ver") if device.get(k)})

    status["display"] = _build_display(status["methods"], meta)
    if status["errors"] and not status["online"]:
        status["error"] = next(iter(status["errors"].values()), None)
    elif status["errors"]:
        status["error"] = ", ".join(f"{k}: {v}" for k, v in status["errors"].items() if v != "timeout")
        if not status["error"]:
            status["error"] = None
    return status


def _first_number(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        return value
    return None


def get_store(config: MarstekConfig) -> MarstekStore:
    return MarstekStore(Path(config.data_file))


def _ensure_poller(config: MarstekConfig) -> None:
    global _POLLER_STARTED
    if not config.enabled:
        return
    with _POLLER_LOCK:
        if _POLLER_STARTED:
            return
        _POLLER_STARTED = True
        thread = threading.Thread(target=_poller_loop, args=(config,), name="marstek-poller", daemon=True)
        thread.start()


def _poller_loop(config: MarstekConfig) -> None:
    while True:
        store = get_store(config)
        ips = [normalize_ip(row["ip"]) for row in store.selected if row.get("ip")]
        if not ips:
            time.sleep(5.0)
            continue
        for ip in ips:
            try:
                status = poll_marstek_device(config, ip)
            except Exception:
                status = {
                    "ip": ip,
                    "online": False,
                    "polled_at": _utc_now_iso(),
                    "methods": {},
                    "display": {},
                    "error": "poll failed",
                }
            _STATUS_CACHE[ip] = status
            time.sleep(max(1.0, config.poll_pause_seconds))
        time.sleep(max(1.0, config.poll_pause_seconds))


def _cached_status(ip: str) -> dict[str, Any] | None:
    return _STATUS_CACHE.get(normalize_ip(ip))


def update_ct_alerts(
    config: MarstekConfig,
    store: MarstekStore,
    statuses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    threshold = max(60, int(config.ct_alert_after_seconds))
    lost_map = dict(store.ct_lost_since())

    by_ip = {normalize_ip(str(s.get("ip"))): s for s in statuses}
    for selected in store.selected:
        dev_id = str(selected.get("id") or "")
        ip = normalize_ip(str(selected.get("ip") or ""))
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
    _ensure_poller(config)
    store = get_store(config)
    statuses: list[dict[str, Any]] = []
    for row in store.selected:
        ip = normalize_ip(row.get("ip") or "")
        if not ip:
            continue
        cached = _cached_status(ip)
        if cached is not None:
            statuses.append(cached)
            continue
        if not _STATUS_CACHE:
            statuses.append(poll_marstek_device(config, ip))
        else:
            statuses.append(
                {
                    "ip": ip,
                    "online": False,
                    "polled_at": _utc_now_iso(),
                    "methods": {},
                    "display": {},
                    "error": "waiting for background poll",
                    "src": row.get("src"),
                    "device": row.get("device"),
                }
            )
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
