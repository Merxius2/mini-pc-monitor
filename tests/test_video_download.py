import unittest
from unittest.mock import patch

from src.config_loader import VideoDownloadConfig
from src.video_download import (
    DownloadJob,
    build_yt_dlp_download_command,
    clear_jobs_display,
    get_video_download_status,
    normalize_download_format,
    reset_jobs_display,
    start_download,
    validate_video_url,
)


class VideoDownloadValidationTests(unittest.TestCase):
    def test_accepts_allowed_host_url(self) -> None:
        config = VideoDownloadConfig()
        ok, msg = validate_video_url(
            "https://www.youporn.com/watch/12345678/video-title/",
            config,
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_accepts_youtube_url(self) -> None:
        config = VideoDownloadConfig()
        ok, msg = validate_video_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ", config)
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_accepts_youtu_be_url(self) -> None:
        config = VideoDownloadConfig()
        ok, _ = validate_video_url("https://youtu.be/dQw4w9WgXcQ", config)
        self.assertTrue(ok)

    def test_rejects_other_hosts(self) -> None:
        config = VideoDownloadConfig()
        ok, msg = validate_video_url("https://example.com/video", config)
        self.assertFalse(ok)
        self.assertIn("allowed site", msg)

    def test_normalize_download_format(self) -> None:
        self.assertEqual(normalize_download_format("video"), "video")
        self.assertEqual(normalize_download_format("mp3"), "audio")
        self.assertEqual(normalize_download_format(None), "video")

    def test_yt_dlp_command_includes_mp3_flags(self) -> None:
        config = VideoDownloadConfig(
            download_dir="/tmp/v",
            video_dir="/tmp/v",
            music_dir="/tmp/m",
        )
        cmd = build_yt_dlp_download_command(
            "https://youtu.be/x",
            config,
            "audio",
        )
        self.assertIn("--audio-format", cmd)
        self.assertIn("mp3", cmd)
        self.assertIn("/tmp/m/", " ".join(cmd))
        self.assertEqual(cmd[-1], "https://youtu.be/x")

    def test_yt_dlp_command_prefers_mp4_for_video(self) -> None:
        config = VideoDownloadConfig(
            download_dir="/tmp/v",
            video_dir="/tmp/v",
            music_dir="/tmp/m",
        )
        cmd = build_yt_dlp_download_command(
            "https://youtu.be/x",
            config,
            "video",
        )
        self.assertIn("/tmp/v/", " ".join(cmd))
        self.assertIn("--merge-output-format", cmd)
        idx = cmd.index("--merge-output-format")
        self.assertEqual(cmd[idx + 1], "mp4")
        self.assertIn("--remux-video", cmd)
        fmt = cmd[cmd.index("-f") + 1]
        self.assertIn("ext=mp4", fmt)


class VideoDownloadJobsClearTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_jobs_display()

    def test_clear_jobs_removes_finished_only_when_active(self) -> None:
        reset_jobs_display()
        from src import video_download as vd_mod

        vd_mod._JOBS["a"] = DownloadJob(
            id="a", url="https://youtu.be/1", status="running"
        )
        vd_mod._JOBS["b"] = DownloadJob(
            id="b", url="https://youtu.be/2", status="done"
        )
        ok, message = clear_jobs_display()
        self.assertTrue(ok)
        self.assertIn("finished", message.lower())
        self.assertIn("a", vd_mod._JOBS)
        self.assertNotIn("b", vd_mod._JOBS)

    def test_clear_jobs_wipes_list_when_idle(self) -> None:
        reset_jobs_display()
        from src import video_download as vd_mod

        vd_mod._JOBS["b"] = DownloadJob(
            id="b", url="https://youtu.be/2", status="done"
        )
        ok, message = clear_jobs_display()
        self.assertTrue(ok)
        self.assertIn("cleared", message.lower())
        self.assertEqual(len(vd_mod._JOBS), 0)


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


class VideoDownloadStatusTests(unittest.TestCase):
    def test_status_reports_yt_dlp_version(self) -> None:
        config = VideoDownloadConfig()
        with patch("src.video_download.yt_dlp_available", return_value=(True, "2024.10.07")):
            status = get_video_download_status(config)
        self.assertTrue(status["yt_dlp_ok"])
        self.assertEqual(status["yt_dlp_version"], "2024.10.07")
        self.assertNotIn("recent_files", status)


if __name__ == "__main__":
    unittest.main()
