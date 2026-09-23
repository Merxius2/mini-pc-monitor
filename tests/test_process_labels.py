import unittest

from src.config_loader import ProcessLabelRule, service_label_for_process


class ProcessLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = [
            ProcessLabelRule(label="Good-search MCP", patterns=["chrome", "tailscale"]),
            ProcessLabelRule(label="AzerothCore", patterns=["worldserver", "mysqld"]),
            ProcessLabelRule(label="Ollama", patterns=["ollama"]),
        ]

    def test_labels_known_processes(self) -> None:
        self.assertEqual(service_label_for_process("chrome", self.rules), "Good-search MCP")
        self.assertEqual(service_label_for_process("tailscaled", self.rules), "Good-search MCP")
        self.assertEqual(service_label_for_process("worldserver", self.rules), "AzerothCore")
        self.assertEqual(service_label_for_process("mysqld", self.rules), "AzerothCore")
        self.assertEqual(service_label_for_process("ollama", self.rules), "Ollama")

    def test_unknown_process(self) -> None:
        self.assertIsNone(service_label_for_process("systemd", self.rules))


if __name__ == "__main__":
    unittest.main()
