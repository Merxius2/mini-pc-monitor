import unittest

from src.config_loader import ProcessLabelRule, process_service_style, service_match_for_process


class ProcessLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = [
            ProcessLabelRule(label="Good-search MCP", color="cyan", patterns=["chrome", "tailscale"]),
            ProcessLabelRule(label="AzerothCore", color="amber", patterns=["worldserver", "mysqld"]),
            ProcessLabelRule(label="Ollama", color="green", patterns=["ollama", "llama-server"]),
            ProcessLabelRule(label="Mini-PC Monitor", color="purple", patterns=["uvicorn"], users=["sylvester"]),
            ProcessLabelRule(label="Pricewatch", color="blue", patterns=["uvicorn"], users=["pricewatch"]),
        ]

    def test_labels_known_processes(self) -> None:
        match = service_match_for_process("chrome", self.rules)
        self.assertEqual(match["label"], "Good-search MCP")
        self.assertEqual(match["color"], "cyan")
        self.assertIn("color: #22d3ee", match["style"])
        tailscale = service_match_for_process("tailscaled", self.rules)
        self.assertEqual(tailscale["label"], "Good-search MCP")
        self.assertEqual(tailscale["color"], "cyan")

        world = service_match_for_process("worldserver", self.rules)
        self.assertEqual(world["label"], "AzerothCore")
        self.assertIn("color: #f59e0b", world["style"])

        mysql = service_match_for_process("mysqld", self.rules)
        self.assertEqual(mysql["color"], "amber")

        ollama = service_match_for_process("ollama", self.rules)
        self.assertEqual(ollama["label"], "Ollama")
        self.assertIn("color: #22c55e", ollama["style"])

        llama_server = service_match_for_process("llama-server", self.rules)
        self.assertEqual(llama_server["label"], "Ollama")

        monitor = service_match_for_process("uvicorn", self.rules, username="sylvester")
        self.assertEqual(monitor["label"], "Mini-PC Monitor")
        self.assertIn("color: #a78bfa", monitor["style"])

        pricewatch = service_match_for_process("uvicorn", self.rules, username="pricewatch")
        self.assertEqual(pricewatch["label"], "Pricewatch")
        self.assertIn("color: #3b82f6", pricewatch["style"])

    def test_unknown_process(self) -> None:
        self.assertIsNone(service_match_for_process("systemd", self.rules))

    def test_process_service_style_fallback(self) -> None:
        style = process_service_style("unknown")
        self.assertIn("color: #22d3ee", style)


if __name__ == "__main__":
    unittest.main()
