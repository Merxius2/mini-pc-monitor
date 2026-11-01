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
        from src.web.app import create_app

        return TestClient(create_app())

    def test_video_download_page_renders_form(self) -> None:
        client = self._client()
        status = {
            "enabled": True,
            "yt_dlp_ok": True,
            "yt_dlp_version": "test",
            "yt_dlp_error": None,
            "video_dir": "/tmp/videos",
            "music_dir": "/tmp/music",
            "download_dir": "/tmp/videos",
            "download_dir_ready": True,
            "allowed_hosts": ["youporn.com"],
            "ffmpeg_ok": True,
            "active_jobs": 0,
            "jobs": [],
        }
        with patch(
            "src.web.routes.get_video_download_status",
            return_value=status,
        ):
            response = client.get("/video-download")
        self.assertEqual(response.status_code, 200)
        self.assertIn("video-download-form", response.text)

    def test_video_download_disabled_returns_404(self) -> None:
        from dataclasses import replace

        from src.config_loader import VideoDownloadConfig
        from src.web.app import create_app

        try:
            from fastapi.testclient import TestClient
        except RuntimeError as exc:
            if "httpx" in str(exc).lower():
                raise unittest.SkipTest("httpx not installed") from exc
            raise

        app = create_app()
        app.state.settings = replace(
            app.state.settings,
            video_download=VideoDownloadConfig(enabled=False),
        )
        response = TestClient(app).get("/video-download")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
