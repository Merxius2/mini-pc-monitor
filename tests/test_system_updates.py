import json
import unittest
from unittest.mock import patch

from src.config_loader import SystemUpdatesConfig
from src.system_updates import _format_upgrade_message, _parse_helper_json, get_system_updates_status


class ParseHelperJsonTests(unittest.TestCase):
    def test_extracts_json_after_apt_noise(self) -> None:
        text = "Reading package lists...\n{\"ok\": true, \"count\": 0}\n"
        data = _parse_helper_json(text)
        self.assertTrue(data["ok"])


class UpgradeMessageTests(unittest.TestCase):
    def test_nothing_installed_but_pending(self) -> None:
        msg = _format_upgrade_message(
            {
                "upgraded": 0,
                "installed": 0,
                "count": 3,
                "not_upgraded": 3,
                "phased": True,
                "kept_back": True,
            }
        )
        self.assertIn("Nothing was installed", msg)
        self.assertIn("3 package(s) still", msg)

    def test_some_installed(self) -> None:
        msg = _format_upgrade_message({"upgraded": 2, "installed": 0, "count": 1})
        self.assertIn("Installed: 2 upgraded", msg)


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
