"""Marstek Venus local API (UDP JSON-RPC on port 30000)."""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import replace
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
_MODE_LABELS = {
    "auto": "Self-consumption",
    "ai": "AI",
    "manual": "Manual",
    "passive": "Passive",
    "ups": "UPS",
}


def format_mode_label(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if not key:
        return None
    return _MODE_LABELS.get(key, str(raw).strip())


def _power_flow(ongrid_power: Any, bat_power: Any) -> str:
    """Marstek ongrid: negative = battery charging (grid import), positive = discharging."""
    grid = _parse_number(ongrid_power)
    if grid is not None:
        if grid < -15:
            return "charging"
        if grid > 15:
            return "discharging"
    bat = _parse_number(bat_power)
    if bat is not None:
        if bat > 15:
            return "charging"
        if bat < -15:
            return "discharging"
    return "idle"


# Open API Rev 3.1 — query methods only (no SetMode, DOD.SET, Led.Ctrl, etc.).
_READ_ONLY_METHODS = frozenset(
    {
        "Marstek.GetDevice",
        "Wifi.GetStatus",
        "BLE.GetStatus",
        "Bat.GetStatus",
        "ES.GetStatus",
        "ES.GetMode",
        "EM.GetStatus",
        "PV.GetStatus",
    }
)

# Core poll path — excludes Bat.GetStatus (reset-prone on firmware < 150 per vendor/HA reports).
_POLL_METHODS_CORE = (
    "Marstek.GetDevice",
    "ES.GetMode",
    "EM.GetStatus",
    "ES.GetStatus",
)


def _poll_methods_for_device(config: MarstekConfig, firmware_ver: int | None) -> list[str]:
    methods = list(_POLL_METHODS_CORE)
    if config.poll_wifi_get_status:
        methods.insert(3, "Wifi.GetStatus")
    if config.poll_bat_get_status and firmware_ver is not None and firmware_ver >= config.bat_get_status_min_firmware:
        methods.insert(2, "Bat.GetStatus")
    return methods


def _parse_firmware_ver(raw: Any) -> int | None:
    value = _parse_number(raw)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def read_only_methods() -> frozenset[str]:
    return _READ_ONLY_METHODS


def _reject_write_method(method: str) -> dict[str, Any] | None:
    if method in _READ_ONLY_METHODS:
        return None
    return {
        "error": {
            "message": f"read-only dashboard: refused Marstek method {method!r}",
            "code": -32001,
        }
    }


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
            self._data = {
                "selected": [],
                "discovered": [],
                "ct_lost_since": {},
                "client": {},
                "polling_enabled": True,
            }
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {
                "selected": [],
                "discovered": [],
                "ct_lost_since": {},
                "client": {},
                "polling_enabled": True,
            }
        self._data.setdefault("selected", [])
        self._data.setdefault("discovered", [])
        self._data.setdefault("ct_lost_since", {})
        self._data.setdefault("client", {})
        if "polling_enabled" not in self._data:
            self._data["polling_enabled"] = True
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
        key = normalize_ip(device_id) or device_id
        for row in self._data["selected"]:
            rid = str(row.get("id") or "")
            rip = normalize_ip(row.get("ip") or "")
            if rid == device_id or rid == key or rip == key:
                row["label"] = label.strip() or row.get("label") or device_id
        self.save()

    def ct_lost_since(self) -> dict[str, str]:
        raw = self._data.get("ct_lost_since") or {}
        return {str(k): str(v) for k, v in raw.items()}

    def set_ct_lost_since(self, mapping: dict[str, str]) -> None:
        self._data["ct_lost_since"] = dict(mapping)
        self.save()

    def client_settings(self) -> dict[str, int]:
        raw = self._data.get("client") or {}
        out: dict[str, int] = {}
        for key in ("bind_port", "udp_port"):
            if key in raw:
                try:
                    out[key] = int(raw[key])
                except (TypeError, ValueError):
                    continue
        return out

    def set_client_settings(self, *, bind_port: int | None = None, udp_port: int | None = None) -> None:
        client = dict(self._data.get("client") or {})
        if bind_port is not None:
            client["bind_port"] = int(bind_port)
        if udp_port is not None:
            client["udp_port"] = int(udp_port)
        self._data["client"] = client
        self.save()

    def polling_enabled(self) -> bool:
        return bool(self._data.get("polling_enabled", True))

    def set_polling_enabled(self, enabled: bool) -> None:
        self._data["polling_enabled"] = bool(enabled)
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
    blocked = _reject_write_method(method)
    if blocked is not None:
        return blocked
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


def empty_display() -> dict[str, Any]:
    return {
        "soc": None,
        "bat_power": None,
        "bat_temp": None,
        "bat_capacity_wh": None,
        "rated_capacity_wh": None,
        "pv_power": None,
        "ongrid_power": None,
        "offgrid_power": None,
        "total_power": None,
        "a_power": None,
        "b_power": None,
        "c_power": None,
        "mode": None,
        "mode_label": None,
        "power_flow": "idle",
        "firmware": None,
        "ct_state": None,
        "ct_connected": False,
        "wifi_rssi": None,
        "ssid": None,
        "total_pv_wh": None,
        "grid_export_wh": None,
        "grid_import_wh": None,
        "ct_input_wh": None,
        "ct_output_wh": None,
    }


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

    ongrid = _first_number(es.get("ongrid_power"), mode.get("ongrid_power"))
    bat_pwr = _first_number(es.get("bat_power"), mode.get("bat_power"))
    raw_mode = mode.get("mode")
    flow = _power_flow(ongrid, bat_pwr)

    return {
        "soc": soc,
        "bat_power": bat_pwr,
        "bat_temp": bat.get("bat_temp"),
        "bat_capacity_wh": bat_cap,
        "rated_capacity_wh": rated,
        "pv_power": _first_number(es.get("pv_power"), mode.get("pv_power")),
        "ongrid_power": ongrid,
        "offgrid_power": _first_number(es.get("offgrid_power"), mode.get("offgrid_power")),
        "total_power": _first_number(em.get("total_power"), mode.get("total_power")),
        "a_power": _first_number(em.get("a_power"), mode.get("a_power")),
        "b_power": _first_number(em.get("b_power"), mode.get("b_power")),
        "c_power": _first_number(em.get("c_power"), mode.get("c_power")),
        "mode": raw_mode,
        "mode_label": format_mode_label(raw_mode),
        "power_flow": flow,
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
    firmware_ver: int | None = None

    with _UDP_LOCK:
        sock = _make_socket(config)
        try:
            reply = _rpc_on_socket(sock, config, ip, "Marstek.GetDevice", req_id=1000)
            if reply.get("result") is not None:
                status["online"] = True
                result = reply["result"]
                status["methods"]["Marstek.GetDevice"] = result
                if isinstance(result, dict):
                    meta["ver"] = result.get("ver")
                    meta["wifi_name"] = result.get("wifi_name")
                    firmware_ver = _parse_firmware_ver(result.get("ver"))
                if reply.get("src"):
                    status["src"] = reply["src"]
                if isinstance(result, dict) and result.get("device"):
                    status["device"] = result.get("device")
            elif reply.get("error"):
                err = reply["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                status["errors"]["Marstek.GetDevice"] = msg

            plan = _poll_methods_for_device(config, firmware_ver)[1:]
            for idx, method in enumerate(plan, start=1):
                if delay > 0:
                    time.sleep(delay)
                reply = _rpc_on_socket(sock, config, ip, method, req_id=1000 + idx)
                if reply.get("result") is not None:
                    status["online"] = True
                    result = reply["result"]
                    status["methods"][method] = result
                    if reply.get("src") and not status.get("src"):
                        status["src"] = reply["src"]
                elif reply.get("error"):
                    err = reply["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    status["errors"][method] = msg
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


def with_store_overrides(config: MarstekConfig) -> MarstekConfig:
    overrides = get_store(config).client_settings()
    if not overrides:
        return config
    kwargs: dict[str, Any] = {}
    if "bind_port" in overrides:
        kwargs["bind_port"] = overrides["bind_port"]
    if "udp_port" in overrides:
        kwargs["udp_port"] = overrides["udp_port"]
    return replace(config, **kwargs)


def label_for_device(store: MarstekStore, ip: str, fallback: str | None = None) -> str:
    ip = normalize_ip(ip)
    for row in store.selected:
        if normalize_ip(row.get("ip") or "") == ip:
            return str(row.get("label") or row.get("src") or fallback or ip)
    return str(fallback or ip)


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
        cfg = with_store_overrides(config)
        store = get_store(config)
        if not store.polling_enabled():
            time.sleep(5.0)
            continue
        ips = [normalize_ip(row["ip"]) for row in store.selected if row.get("ip")]
        if not ips:
            time.sleep(5.0)
            continue
        for ip in ips:
            try:
                status = poll_marstek_device(cfg, ip)
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


def get_marstek_summary(config: MarstekConfig) -> dict[str, Any]:
    if not config.enabled:
        return {"enabled": False, "devices": [], "count": 0}
    store = get_store(config)
    if not store.polling_enabled():
        return {
            "enabled": True,
            "polling_enabled": False,
            "devices": [],
            "count": 0,
            "has_ct_alerts": False,
            "paused": True,
        }
    dash = get_marstek_dashboard(config)
    store = get_store(config)
    rows: list[dict[str, Any]] = []
    for dev in dash.get("devices") or []:
        ip = normalize_ip(dev.get("ip") or "")
        disp = dev.get("display") or {}
        rows.append(
            {
                "ip": ip,
                "name": label_for_device(store, ip, dev.get("src")),
                "online": bool(dev.get("online")),
                "soc": disp.get("soc"),
                "mode_label": disp.get("mode_label") or disp.get("mode"),
                "power_flow": disp.get("power_flow") or "idle",
                "ongrid_power": disp.get("ongrid_power"),
                "ct_connected": disp.get("ct_connected"),
            }
        )
    return {
        "enabled": True,
        "polling_enabled": True,
        "devices": rows,
        "count": len(rows),
        "has_ct_alerts": dash.get("has_ct_alerts"),
        "paused": False,
    }


def get_marstek_dashboard(config: MarstekConfig) -> dict[str, Any]:
    if not config.enabled:
        return {"enabled": False}
    cfg = with_store_overrides(config)
    store = get_store(config)
    polling_on = store.polling_enabled()
    if polling_on:
        _ensure_poller(config)
    statuses: list[dict[str, Any]] = []
    for row in store.selected:
        ip = normalize_ip(row.get("ip") or "")
        if not ip:
            continue
        if not polling_on:
            statuses.append(
                {
                    "ip": ip,
                    "online": False,
                    "polled_at": _utc_now_iso(),
                    "methods": {},
                    "display": empty_display(),
                    "error": "monitoring paused — no UDP traffic",
                    "src": row.get("src"),
                    "device": row.get("device"),
                }
            )
            continue
        cached = _cached_status(ip)
        if cached is not None:
            statuses.append(cached)
            continue
        statuses.append(
            {
                "ip": ip,
                "online": False,
                "polled_at": _utc_now_iso(),
                "methods": {},
                "display": empty_display(),
                "error": "waiting for background poll",
                "src": row.get("src"),
                "device": row.get("device"),
            }
        )
    alerts = update_ct_alerts(config, store, statuses) if polling_on else []
    return {
        "enabled": True,
        "polling_enabled": polling_on,
        "config": cfg,
        "selected": store.selected,
        "selected_ids": {str(s.get("id") or "") for s in store.selected if s.get("id")},
        "discovered": store.discovered,
        "devices": statuses,
        "alerts": alerts,
        "has_ct_alerts": bool(alerts),
    }
