import unittest

from src.config_loader import PricewatchConfig
from src.service_logs import _journal_entries, _pricewatch_summary, parse_journal_line


class ServiceLogsTests(unittest.TestCase):
    def test_parse_journal_line(self) -> None:
        line = "2026-09-22T12:16:10+0200 sylvester-MINIPC-PN50 node[399249]: good-search MCP server listening"
        parsed = parse_journal_line(line)
        self.assertEqual(parsed["time"], "12:16:10")
        self.assertIn("listening", parsed["message"])

    def test_parse_ollama_gin_line(self) -> None:
        line = (
            "2026-09-22T19:03:45+0200 host ollama[6342]: "
            "[GIN] 2026/09/22 - 19:03:45 | 200 | 404.731µs | 127.0.0.1 | GET \"/api/tags\""
        )
        parsed = parse_journal_line(line)
        self.assertEqual(parsed["time"], "19:03:45")
        self.assertIn("GET /api/tags", parsed["message"])
        self.assertIn("200", parsed["message"])

    def test_pricewatch_summary(self) -> None:
        from unittest.mock import patch

        config = PricewatchConfig(
            health_url="http://127.0.0.1:8081/health",
            stats_url="http://127.0.0.1:8081/api/stats",
        )
        with patch("src.service_logs._fetch_json") as fetch:
            fetch.side_effect = [
                {"status": "ok", "model": "llama3.2", "good_search": {"reachable": True}},
                {"total_items": 5, "enabled_items": 4, "alerts_active": 1},
            ]
            badges, lines = _pricewatch_summary(config)
        self.assertEqual(badges[0]["label"], "healthy")
        self.assertTrue(any("4/5 items" in line for line in lines))

    def test_journal_entries_newest_first(self) -> None:
        from unittest.mock import patch

        fake_output = "\n".join(
            [
                "2026-09-22T12:00:01+0200 host svc[1]: first",
                "2026-09-22T12:00:02+0200 host svc[1]: second",
                "2026-09-22T12:00:03+0200 host svc[1]: third",
            ]
        )
        with patch("src.service_logs._run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = fake_output
            entries, error = _journal_entries("example.service", lines=3)
        self.assertIsNone(error)
        self.assertEqual(entries[0]["message"], "third")
        self.assertEqual(entries[-1]["message"], "first")


if __name__ == "__main__":
    unittest.main()
