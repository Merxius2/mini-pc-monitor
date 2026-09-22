import unittest

from src.service_logs import parse_journal_line


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


if __name__ == "__main__":
    unittest.main()
