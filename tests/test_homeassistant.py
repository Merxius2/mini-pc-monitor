import unittest
from unittest.mock import patch

from src.config_loader import HomeAssistantConfig
from src.homeassistant import get_homeassistant_status


class HomeAssistantStatusTests(unittest.TestCase):
    def test_online_with_rflink(self) -> None:
        config = HomeAssistantConfig()
        with patch("src.homeassistant._systemd_active", return_value="active"), patch(
            "src.homeassistant._container_state", return_value="running"
        ), patch("src.homeassistant._http_reachable", return_value=True), patch(
            "src.homeassistant._rflink_from_logs", return_value=True
        ):
            status = get_homeassistant_status(config)
        assert status is not None
        self.assertTrue(status["ready"])
        self.assertTrue(status["rflink_connected"])
        self.assertEqual(status["overall"], "ok")

    def test_container_missing(self) -> None:
        config = HomeAssistantConfig()
        with patch("src.homeassistant._systemd_active", return_value="inactive"), patch(
            "src.homeassistant._container_state", return_value="missing"
        ), patch("src.homeassistant._http_reachable", return_value=False):
            status = get_homeassistant_status(config)
        assert status is not None
        self.assertFalse(status["ready"])
        self.assertEqual(status["container"], "missing")


if __name__ == "__main__":
    unittest.main()
