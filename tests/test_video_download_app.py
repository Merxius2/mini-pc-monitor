import unittest
from unittest.mock import patch


class VideoDownloadAppTests(unittest.TestCase):
    def _client(self):
        try:
            from fastapi.testclient import TestClient
        except RuntimeError as exc:
            if "httpx" in str(exc).lower():
                raise unittest.SkipTest("httpx not installed") from exc
            raise
        from src.web.video_download_app import create_app

        return TestClient(create_app())

    def test_health(self) -> None:
        client = self._client()
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app"], "video-download")

    def test_home_renders_form(self) -> None:
        client = self._client()
        status = {
            "enabled": True,
            "yt_dlp_ok": True,
            "yt_dlp_version": "test",
            "yt_dlp_error": None,
            "download_dir": "/tmp/videos",
            "download_dir_ready": True,
            "allowed_hosts": ["youporn.com"],
            "active_jobs": 0,
            "jobs": [],
            "recent_files": [],
        }
        with patch("src.web.video_download_app.get_video_download_status", return_value=status):
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("video-download-form", response.text)


if __name__ == "__main__":
    unittest.main()
