import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config_loader import ServiceConfig, ServiceStateConfig, Settings
from src.service_state import load_state, set_unit_desired, snapshot_managed


class ServiceStatePersistenceTests(unittest.TestCase):
    def test_set_and_load_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            cfg = ServiceStateConfig(enabled=True, state_file=str(path))
            set_unit_desired(cfg, "domoticz.service", False)
            data = load_state(cfg)
            self.assertFalse(data["units"]["domoticz.service"])
            self.assertTrue(path.is_file())

    def test_snapshot_managed_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            cfg = ServiceStateConfig(enabled=True, state_file=str(path))
            settings = Settings(
                services=[
                    ServiceConfig(unit="a.service", label="A", manage=True),
                    ServiceConfig(unit="b.service", label="B", manage=False),
                ],
                service_state=cfg,
            )

            def fake_active(unit: str) -> bool:
                return unit == "a.service"

            with patch("src.service_state._unit_active", side_effect=fake_active):
                snapshot_managed(settings)
            data = json.loads(path.read_text())
            self.assertTrue(data["units"]["a.service"])
            self.assertNotIn("b.service", data["units"])


if __name__ == "__main__":
    unittest.main()
