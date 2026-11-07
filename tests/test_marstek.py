import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.config_loader import MarstekConfig
from src.marstek import (
    MarstekStore,
    _device_from_message,
    update_ct_alerts,
)


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
