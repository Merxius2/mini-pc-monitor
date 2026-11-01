import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config_loader import VideoDownloadConfig
from src.video_download import (
    DownloadJob,
    build_yt_dlp_download_command,
    clear_jobs_display,
    get_video_download_status,
    normalize_download_format,
    parse_form_bool,
    parse_push_mode,
    reset_jobs_display,
    resolve_media_file,
    schedule_storage_delete,
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

    def test_parse_form_bool(self) -> None:
        self.assertTrue(parse_form_bool("true"))
        self.assertFalse(parse_form_bool("false"))

    def test_parse_push_mode(self) -> None:
        self.assertEqual(parse_push_mode("off"), (False, False))
        self.assertEqual(parse_push_mode("push"), (True, False))
        self.assertEqual(parse_push_mode("push_purge"), (True, True))

    def test_job_file_url_when_done(self) -> None:
        job = DownloadJob(
            id="x",
            url="https://youtu.be/a",
            status="done",
            output_category="video",
            output_name="clip.mp4",
        )
        self.assertIn("/video-download/files/video/", job.file_url or "")
        self.assertIn("clip.mp4", job.file_url or "")

    def test_resolve_media_file_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = VideoDownloadConfig(
                download_dir=tmp,
                video_dir=tmp,
                music_dir=str(Path(tmp) / "m"),
            )
            self.assertIsNone(resolve_media_file(config, "video", "../etc/passwd"))
            self.assertIsNone(resolve_media_file(config, "other", "a.mp4"))

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

    def test_delete_after_push_only_when_push_enabled(self) -> None:
        config = VideoDownloadConfig()
        with patch("src.video_download.yt_dlp_available", return_value=(True, "2024.10.01")):
            with patch("src.video_download.threading.Thread") as thread_cls:
                thread_cls.return_value.start = lambda: None
                start_download(
                    "https://www.youporn.com/watch/1/test/",
                    config,
                    push_to_device=False,
                    delete_after_push=True,
                )
        from src import video_download as vd_mod

        job = next(iter(vd_mod._JOBS.values()))
        self.assertFalse(job.delete_after_push)
        reset_jobs_display()

    def test_scheduled_delete_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "song.mp3"
            path.write_bytes(b"mp3")
            config = VideoDownloadConfig(
                download_dir=tmp,
                video_dir=tmp,
                music_dir=tmp,
                delete_after_push_seconds=1,
            )
            job_id = "job1"
            vd_mod = __import__("src.video_download", fromlist=["*"])
            vd_mod._JOBS[job_id] = DownloadJob(
                id=job_id,
                url="https://youtu.be/x",
                status="done",
                delete_after_push=True,
                push_to_device=True,
                output_category="music",
                output_name="song.mp3",
            )
            schedule_storage_delete(config, job_id, "music", "song.mp3", 1)
            import time

            time.sleep(1.3)
            self.assertFalse(path.is_file())
            job = vd_mod._JOBS[job_id]
            self.assertTrue(job.storage_purged)
            reset_jobs_display()


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
