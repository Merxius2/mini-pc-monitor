import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config_loader import VideoDownloadConfig
from src.video_download import (
    get_video_download_status,
    list_recent_downloads,
    start_download,
    validate_video_url,
)


class VideoDownloadValidationTests(unittest.TestCase):
    def test_accepts_youporn_url(self) -> None:
        config = VideoDownloadConfig()
        ok, msg = validate_video_url(
            "https://www.youporn.com/watch/12345678/video-title/",
            config,
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_rejects_other_hosts(self) -> None:
        config = VideoDownloadConfig()
        ok, msg = validate_video_url("https://example.com/video", config)
        self.assertFalse(ok)
        self.assertIn("allowed site", msg)


class VideoDownloadActionsTests(unittest.TestCase):
    def test_start_download_spawns_background_job(self) -> None:
        config = VideoDownloadConfig()
        with patch("src.video_download.yt_dlp_available", return_value=(True, "2024.10.01")):
            with patch("src.video_download.threading.Thread") as thread_cls:
                thread_cls.return_value.start = lambda: None
                ok, message, job_id = start_download(
                    "https://www.youporn.com/watch/1/test/",
                    config,
                )
        self.assertTrue(ok)
        self.assertIsNotNone(job_id)
        self.assertIn("started", message.lower())
        thread_cls.assert_called_once()

    def test_recent_files_sorted_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old.mp4"
            new = root / "new.mp4"
            old.write_bytes(b"x")
            new.write_bytes(b"xx")
            old.touch()
            new.touch()
            new_path_mtime = new.stat().st_mtime
            old_path_mtime = old.stat().st_mtime
            if new_path_mtime <= old_path_mtime:
                import os
                import time

                time.sleep(0.02)
                os.utime(new, None)

            config = VideoDownloadConfig(download_dir=tmp, max_recent_files=5)
            files = list_recent_downloads(config)
            self.assertEqual(len(files), 2)
            self.assertEqual(files[0]["name"], "new.mp4")


class VideoDownloadStatusTests(unittest.TestCase):
    def test_status_reports_yt_dlp_version(self) -> None:
        config = VideoDownloadConfig()
        with patch("src.video_download.yt_dlp_available", return_value=(True, "2024.10.07")):
            status = get_video_download_status(config)
        self.assertTrue(status["yt_dlp_ok"])
        self.assertEqual(status["yt_dlp_version"], "2024.10.07")


if __name__ == "__main__":
    unittest.main()
