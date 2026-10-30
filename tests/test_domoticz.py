import unittest
from unittest.mock import patch

from src.config_loader import DomoticzConfig
from src.domoticz import get_domoticz_status


class DomoticzStatusTests(unittest.TestCase):
    def test_online(self) -> None:
        config = DomoticzConfig()
        with patch("src.domoticz._systemd_active", return_value="active"), patch(
            "src.domoticz._container_state", return_value="running"
        ), patch("src.domoticz._http_reachable", return_value=True):
            status = get_domoticz_status(config)
        assert status is not None
        self.assertTrue(status["ready"])


if __name__ == "__main__":
    unittest.main()
