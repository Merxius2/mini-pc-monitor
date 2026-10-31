import json
import unittest
from unittest.mock import patch

from src.config_loader import SystemUpdatesConfig
from src.system_updates import get_system_updates_status


class SystemUpdatesStatusTests(unittest.TestCase):
    def test_parses_helper_json(self) -> None:
        config = SystemUpdatesConfig()
        payload = {
            "count": 2,
            "packages": [
                {"name": "curl", "version": "8.5.0-1"},
                {"name": "docker.io", "version": "28.0.0-1"},
            ],
            "reboot_required": True,
            "reboot_hint": "linux-image-7.0.0-42-generic",
        }

        def fake_run(cmd: list[str]):
            class Result:
                returncode = 0
                stdout = json.dumps(payload)
                stderr = ""

            return Result()

        with patch("src.system_updates._run", fake_run):
            status = get_system_updates_status(config)

        self.assertEqual(status["count"], 2)
        self.assertTrue(status["reboot_required"])
        self.assertEqual(status["overall"], "amber")
        self.assertEqual(status["packages"][0]["name"], "curl")


if __name__ == "__main__":
    unittest.main()
