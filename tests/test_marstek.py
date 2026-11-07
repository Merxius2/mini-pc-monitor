import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.config_loader import MarstekConfig
from src.marstek import (
    MarstekStore,
    _build_display,
    _device_from_message,
    _power_flow,
    format_mode_label,
    marstek_rpc,
    normalize_ip,
    read_only_methods,
    update_ct_alerts,
)


class NormalizeIpTests(unittest.TestCase):
    def test_strips_zero_padded_octets(self) -> None:
        self.assertEqual(normalize_ip("192.168.01.27"), "192.168.1.27")


class BuildDisplayTests(unittest.TestCase):
    def test_merges_es_get_mode_when_es_status_missing(self) -> None:
        display = _build_display(
            {
                "ES.GetMode": {
                    "mode": "Auto",
                    "bat_soc": 91,
                    "ongrid_power": -300,
                    "ct_state": 1,
                    "total_power": -12,
                },
                "Bat.GetStatus": {"soc": 91, "bat_capacity": 4600, "rated_capacity": 5120},
            },
            {},
        )
        self.assertEqual(display["soc"], 91)
        self.assertEqual(display["mode_label"], "Self-consumption")
        self.assertEqual(display["ongrid_power"], -300)
        self.assertEqual(display["power_flow"], "charging")
        self.assertEqual(display["ct_state"], 1)


class PowerFlowTests(unittest.TestCase):
    def test_negative_grid_is_charging(self) -> None:
        self.assertEqual(_power_flow(-200, None), "charging")
        self.assertEqual(_power_flow(200, None), "discharging")


class ModeLabelTests(unittest.TestCase):
    def test_auto_is_self_consumption(self) -> None:
        self.assertEqual(format_mode_label("Auto"), "Self-consumption")


class ReadOnlyApiTests(unittest.TestCase):
    def test_poll_methods_are_whitelisted(self) -> None:
        allowed = read_only_methods()
        from src.marstek import _POLL_METHODS_CORE, _poll_methods_for_device

        for name in _POLL_METHODS_CORE:
            self.assertIn(name, allowed)
        cfg = MarstekConfig(poll_bat_get_status=True, bat_get_status_min_firmware=150)
        plan = _poll_methods_for_device(cfg, 150)
        self.assertIn("Bat.GetStatus", plan)
        plan_old = _poll_methods_for_device(cfg, 148)
        self.assertNotIn("Bat.GetStatus", plan_old)

    def test_set_mode_is_not_sent(self) -> None:
        cfg = MarstekConfig()
        reply = marstek_rpc(cfg, "192.168.1.1", "ES.SetMode", req_id=1)
        self.assertEqual(reply["error"]["code"], -32001)
        self.assertIn("read-only", reply["error"]["message"])


class DeviceFromMessageTests(unittest.TestCase):
    def test_parses_get_device_result(self) -> None:
        message = {
            "src": "VENUS-AABB",
            "result": {
                "device": "Venus",
                "ip": "192.168.1.50",
                "ble_mac": "aa:bb",
                "wifi_name": "home",
            },
        }
        device = _device_from_message(message, fallback_ip="192.168.1.50")
        self.assertIsNotNone(device)
        assert device is not None
        self.assertEqual(device["ip"], "192.168.1.50")
        self.assertEqual(device["src"], "VENUS-AABB")


class MarstekStoreTests(unittest.TestCase):
    def test_toggle_selected_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marstek.json"
            config = MarstekConfig(data_file=str(path))
            store = MarstekStore(path)
            store.toggle_selected(
                {"id": "VENUS-1", "ip": "192.168.1.50", "src": "VENUS-1"},
                on=True,
            )
            store = MarstekStore(path)
            self.assertEqual(len(store.selected), 1)
            store.toggle_selected({"id": "VENUS-1", "ip": "192.168.1.50"}, on=False)
            self.assertEqual(store.selected, [])


class CtAlertTests(unittest.TestCase):
    def test_ct_lost_triggers_after_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marstek.json"
            path.write_text(
                json.dumps(
                    {
                        "selected": [{"id": "d1", "ip": "192.168.1.50", "label": "Bat A"}],
                        "discovered": [],
                        "ct_lost_since": {
                            "d1": (datetime.now(timezone.utc) - timedelta(minutes=6)).replace(microsecond=0).isoformat()
                        },
                    }
                ),
                encoding="utf-8",
            )
            store = MarstekStore(path)
            config = MarstekConfig(data_file=str(path), ct_alert_after_seconds=300)
            statuses = [
                {
                    "ip": "192.168.1.50",
                    "online": True,
                    "display": {"ct_state": 0},
                }
            ]
            alerts = update_ct_alerts(config, store, statuses)
            self.assertEqual(len(alerts), 1)
            self.assertIn("Bat A", alerts[0]["message"])

    def test_ct_restored_clears_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marstek.json"
            path.write_text(
                json.dumps(
                    {
                        "selected": [{"id": "d1", "ip": "192.168.1.50", "label": "Bat A"}],
                        "discovered": [],
                        "ct_lost_since": {"d1": datetime.now(timezone.utc).isoformat()},
                    }
                ),
                encoding="utf-8",
            )
            store = MarstekStore(path)
            config = MarstekConfig(data_file=str(path))
            statuses = [
                {
                    "ip": "192.168.1.50",
                    "online": True,
                    "display": {"ct_state": 1},
                }
            ]
            alerts = update_ct_alerts(config, store, statuses)
            self.assertEqual(alerts, [])
            self.assertEqual(store.ct_lost_since(), {})


if __name__ == "__main__":
    unittest.main()
