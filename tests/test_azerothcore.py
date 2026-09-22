import unittest
from unittest.mock import patch

from src.azerothcore import _level, _summary, get_azerothcore_status
from src.config_loader import AzerothCoreConfig


class AzerothCoreStatusTests(unittest.TestCase):
    def test_level_running_with_port(self) -> None:
        level, state = _level(running=True, port=3724, port_open=True)
        self.assertEqual(level, "ok")
        self.assertEqual(state, "running")

    def test_level_starting_without_port(self) -> None:
        level, state = _level(running=True, port=8085, port_open=False)
        self.assertEqual(level, "amber")
        self.assertEqual(state, "starting")

    def test_summary_loading(self) -> None:
        components = [
            {"key": "world", "running": True, "port_open": False},
            {"key": "auth", "running": True, "port_open": True},
        ]
        text = _summary(False, components)
        self.assertIn("loading", text.lower())

    @patch("src.azerothcore._port_open", return_value=True)
    @patch("src.azerothcore._process_info")
    @patch("src.azerothcore._batch_service_states")
    @patch("src.azerothcore._run")
    def test_get_status_ready(
        self,
        mock_run,
        mock_batch,
        mock_process,
        _mock_port,
    ) -> None:
        mock_batch.return_value = {
            "mysql.service": {"active": "active", "enabled": "enabled"},
            "azerothcore.service": {"active": "active", "enabled": "disabled"},
        }
        mock_process.side_effect = [
            {"running": True, "pid": 1, "memory_mb": 50.0, "cpu_percent": 0.1},
            {"running": True, "pid": 2, "memory_mb": 800.0, "cpu_percent": 5.0},
        ]
        mock_run.return_value = unittest.mock.Mock(returncode=0)

        status = get_azerothcore_status(AzerothCoreConfig())
        self.assertIsNotNone(status)
        assert status is not None
        self.assertTrue(status["ready"])
        self.assertEqual(len(status["components"]), 4)


if __name__ == "__main__":
    unittest.main()
