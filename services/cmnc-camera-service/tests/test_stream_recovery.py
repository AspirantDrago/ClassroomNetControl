import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from cmnc_camera_service import main as camera


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.stderr = None
        self.finished = asyncio.get_running_loop().create_future()
        if returncode is not None:
            self.finished.set_result(returncode)

    async def wait(self):
        return await asyncio.shield(self.finished)

    def terminate(self):
        self.returncode = -15
        if not self.finished.done():
            self.finished.set_result(self.returncode)

    def kill(self):
        self.terminate()


class StreamRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.url = "rtsp://user:secret@example.invalid/stream"
        self.key = camera.build_stream_key(self.url, "main")
        self.stream = camera.SharedCameraStream(
            id="test", key=self.key, rtsp_url=self.url, quality="main",
            hls_dir=Path(self.directory.name), created_at=datetime.now(timezone.utc),
        )
        self.stream.viewer_session_ids.add("viewer")
        camera.shared_streams.clear()
        camera.shared_streams[self.key] = self.stream
        self.delay = camera.settings.rtsp_reconnect_delay_seconds
        camera.settings.rtsp_reconnect_delay_seconds = 0.1

    async def asyncTearDown(self):
        await camera.stop_stream_process(self.stream)
        camera.shared_streams.clear()
        camera.settings.rtsp_reconnect_delay_seconds = self.delay
        self.directory.cleanup()

    async def start_recovery(self, exitcode, failures=0):
        initial = FakeProcess(exitcode)
        next_process = FakeProcess()
        self.stream.process = initial
        spawned = asyncio.Event()
        attempts = 0

        async def spawn(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= failures:
                raise OSError("temporary spawn failure")
            spawned.set()
            return next_process

        with patch.object(camera.asyncio, "create_subprocess_exec", side_effect=spawn):
            self.stream.restart_task = asyncio.create_task(
                camera.watch_ffmpeg_process(self.key, self.stream.id, initial)
            )
            await asyncio.wait_for(spawned.wait(), 2)
            self.assertIs(self.stream.process, next_process)
            self.assertEqual(self.stream.viewer_session_ids, {"viewer"})
            self.assertTrue(self.stream.hls_dir.exists())
            self.assertEqual(attempts, failures + 1)
            await camera.stop_stream_process(self.stream)
            self.assertEqual(next_process.returncode, -15)

    async def test_reconnects_after_clean_eof(self):
        await self.start_recovery(0)

    async def test_reconnects_after_error(self):
        await self.start_recovery(1)

    async def test_retries_subprocess_start_failure(self):
        await self.start_recovery(0, failures=1)

    async def test_does_not_restart_without_viewers(self):
        self.stream.viewer_session_ids.clear()
        process = FakeProcess(0)
        self.stream.process = process
        with patch.object(camera.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as spawn:
            await camera.watch_ffmpeg_process(self.key, self.stream.id, process)
            spawn.assert_not_awaited()

    async def test_stopping_cancels_delayed_reconnect(self):
        camera.settings.rtsp_reconnect_delay_seconds = 10
        process = FakeProcess(0)
        self.stream.process = process
        with patch.object(camera.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as spawn:
            self.stream.restart_task = asyncio.create_task(
                camera.watch_ffmpeg_process(self.key, self.stream.id, process)
            )
            await asyncio.sleep(0)
            await camera.stop_stream_process(self.stream)
            spawn.assert_not_awaited()
            self.assertIsNone(self.stream.restart_task)
            self.assertIsNone(self.stream.process)

    async def test_new_viewer_reuses_stream_during_reconnect(self):
        self.stream.restart_task = asyncio.create_task(asyncio.sleep(10))
        with patch.object(camera.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as spawn:
            stream = await camera.get_or_start_shared_stream(self.url, "main")
            self.assertIs(stream, self.stream)
            spawn.assert_not_awaited()
        self.stream.viewer_session_ids.clear()
        self.assertFalse(camera.is_stream_process_running(self.stream))

    async def test_prunes_only_old_unreferenced_segments(self):
        now = datetime.now(timezone.utc).timestamp()
        for name in ("segment_00000.ts", "segment_00001.ts", "segment_00002.ts"):
            path = self.stream.hls_dir / name
            path.write_bytes(b"segment")
            os.utime(path, (now - 60, now - 60))
        recent = self.stream.hls_dir / "segment_00002.ts"
        os.utime(recent, (now, now))
        (self.stream.hls_dir / "index.m3u8").write_text("#EXTM3U\nsegment_00001.ts\n")
        camera.prune_old_hls_segments(self.stream)
        self.assertFalse((self.stream.hls_dir / "segment_00000.ts").exists())
        self.assertTrue((self.stream.hls_dir / "segment_00001.ts").exists())
        self.assertTrue(recent.exists())

    async def test_command_preserves_hls_history_and_limits_network_wait(self):
        command = camera.build_ffmpeg_command(self.stream)
        self.assertIn("append_list", command[command.index("-hls_flags") + 1])
        self.assertEqual(command[command.index("-timeout") + 1], "10000000")
        if camera.settings.audio_mode == "aac":
            self.assertIn("aresample=async=1:first_pts=0", command)

    async def test_log_redaction(self):
        text = camera.sanitize_rtsp_urls("Input: " + self.url)
        self.assertNotIn("secret", text)
        self.assertNotIn("user:", text)
        self.assertIn("example.invalid/stream", text)


if __name__ == "__main__":
    unittest.main()
