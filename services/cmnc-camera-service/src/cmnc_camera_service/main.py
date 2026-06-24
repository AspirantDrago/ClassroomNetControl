import asyncio
import hashlib
import logging
import shutil
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from cmnc_camera_service.schemas import (
    CameraSessionCreateRequest,
    CameraSessionResponse,
    CameraSessionStopResponse,
    HealthResponse,
)
from cmnc_camera_service.session_store import CameraSession, CameraSessionStore
from cmnc_camera_service.settings import settings

logger = logging.getLogger("cmnc_camera_service")

session_store = CameraSessionStore(ttl_seconds=settings.session_ttl_seconds)
hls_root_dir = Path(settings.hls_root_dir)


@dataclass(slots=True)
class SharedCameraStream:
    id: str
    key: str
    rtsp_url: str
    quality: str
    hls_dir: Path
    created_at: datetime
    viewer_session_ids: set[str] = field(default_factory=set)
    process: asyncio.subprocess.Process | None = None
    last_viewer_left_at: datetime | None = None


shared_streams: dict[str, SharedCameraStream] = {}
shared_streams_lock = asyncio.Lock()


async def cleanup_expired_sessions() -> None:
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)

        for session in session_store.pop_expired():
            await release_session(session)

        await cleanup_idle_streams()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    hls_root_dir.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(cleanup_expired_sessions())

    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task

        async with shared_streams_lock:
            streams = list(shared_streams.values())
            shared_streams.clear()

        for stream in streams:
            await stop_stream_process(stream)
            remove_stream_dir(stream)


app = FastAPI(title=settings.service_name, lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.post(
    "/internal/camera/sessions",
    response_model=CameraSessionResponse,
    status_code=201,
)
async def create_camera_session(
    payload: CameraSessionCreateRequest,
) -> CameraSessionResponse:
    rtsp_url = payload.rtsp_url.strip()

    if not rtsp_url.startswith(("rtsp://", "rtsps://")):
        raise HTTPException(status_code=422, detail="rtsp_url must start with rtsp:// or rtsps://")

    stream = await get_or_start_shared_stream(rtsp_url=rtsp_url, quality=payload.quality)
    session = session_store.create(
        rtsp_url=rtsp_url,
        quality=payload.quality,
        stream_key=stream.key,
        hls_dir=stream.hls_dir,
    )

    async with shared_streams_lock:
        current_stream = shared_streams.get(stream.key)

        if current_stream is None:
            session_store.delete(session.id)
            raise HTTPException(status_code=503, detail="Camera stream is not available")

        current_stream.viewer_session_ids.add(session.id)
        current_stream.last_viewer_left_at = None
        viewer_count = len(current_stream.viewer_session_ids)

    logger.info(
        "Attached camera session[%s] to shared stream[%s], viewers=%s",
        session.id,
        stream.id,
        viewer_count,
    )

    return CameraSessionResponse(
        session_id=session.id,
        mode="hls",
        quality=session.quality,
        stream_path=f"/internal/camera/sessions/{session.id}/hls/index.m3u8",
        expires_in_seconds=settings.session_ttl_seconds,
    )


@app.post(
    "/internal/camera/sessions/{session_id}/stop",
    response_model=CameraSessionStopResponse,
)
async def stop_camera_session(session_id: str) -> CameraSessionStopResponse:
    session = session_store.delete(session_id)

    if session is not None:
        await release_session(session)

    return CameraSessionStopResponse(
        stopped=session is not None,
        session_id=session_id,
    )


@app.get("/internal/camera/sessions/{session_id}/hls/{filename}")
async def get_camera_hls_file(session_id: str, filename: str) -> FileResponse:
    session = session_store.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Camera session not found")

    if not is_allowed_hls_filename(filename):
        raise HTTPException(status_code=404, detail="HLS file not found")

    path = session.hls_dir / filename

    if filename == "index.m3u8":
        await wait_for_file(path)

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="HLS file not found")

    return FileResponse(
        path,
        media_type=get_hls_media_type(filename),
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def get_or_start_shared_stream(rtsp_url: str, quality: str) -> SharedCameraStream:
    stream_key = build_stream_key(rtsp_url=rtsp_url, quality=quality)

    async with shared_streams_lock:
        existing_stream = shared_streams.get(stream_key)

        if existing_stream is not None and is_stream_process_running(existing_stream):
            logger.info("Reusing shared stream[%s] for quality=%s", existing_stream.id, quality)
            return existing_stream

        if existing_stream is not None:
            logger.warning("Replacing inactive shared stream[%s]", existing_stream.id)
            shared_streams.pop(stream_key, None)
            await stop_stream_process(existing_stream)
            remove_stream_dir(existing_stream)

        stream = SharedCameraStream(
            id=stream_key[:24],
            key=stream_key,
            rtsp_url=rtsp_url,
            quality=quality,
            hls_dir=hls_root_dir / stream_key,
            created_at=datetime.now(timezone.utc),
        )
        remove_stream_dir(stream)
        stream.hls_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg_command = build_ffmpeg_command(stream)
        logger.info(
            "Starting shared ffmpeg[%s]: %s",
            stream.id,
            " ".join(shlex.quote(arg) for arg in ffmpeg_command),
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            remove_stream_dir(stream)
            raise HTTPException(status_code=502, detail=f"Could not start ffmpeg: {exc}") from exc

        stream.process = process
        shared_streams[stream.key] = stream
        asyncio.create_task(log_ffmpeg_stderr(stream.id, process))
        asyncio.create_task(watch_ffmpeg_process(stream.key, stream.id, process))
        return stream


def build_ffmpeg_command(stream: SharedCameraStream) -> list[str]:
    playlist_path = stream.hls_dir / "index.m3u8"
    segment_path = stream.hls_dir / "segment_%05d.ts"
    fps = settings.transcode_fps
    keyframe_interval = max(settings.hls_time_seconds * fps, fps)
    video_mode = get_video_mode()

    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        settings.rtsp_transport,
        "-fflags",
        "+discardcorrupt+genpts",
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        stream.rtsp_url,
        "-map",
        "0:v:0",
    ]

    if settings.audio_mode != "none":
        command.extend(["-map", "0:a:0?"])

    command.extend(["-sn", "-dn"])

    if video_mode == "copy":
        command.extend(["-c:v", "copy"])
    elif video_mode == "hevc":
        command.extend([
            "-vf",
            build_video_filter(fps),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-enc_time_base",
            f"1:{fps}",
            "-c:v",
            "libx265",
            "-preset",
            settings.transcode_preset,
            "-crf",
            str(settings.transcode_crf),
            "-pix_fmt",
            "yuv420p",
            "-tag:v",
            "hvc1",
            "-g",
            str(keyframe_interval),
            "-keyint_min",
            str(keyframe_interval),
            "-sc_threshold",
            "0",
            "-force_key_frames",
            f"expr:gte(t,n_forced*{settings.hls_time_seconds})",
            "-x265-params",
            f"keyint={keyframe_interval}:min-keyint={keyframe_interval}:scenecut=0:log-level=warning",
        ])
    else:
        command.extend([
            "-vf",
            build_video_filter(fps),
            "-r",
            str(fps),
            "-fps_mode",
            "cfr",
            "-enc_time_base",
            f"1:{fps}",
            "-c:v",
            "libx264",
            "-preset",
            settings.transcode_preset,
            "-tune",
            "zerolatency",
            "-profile:v",
            settings.transcode_profile,
            "-level:v",
            settings.transcode_level,
            "-crf",
            str(settings.transcode_crf),
            "-pix_fmt",
            "yuv420p",
            "-g",
            str(keyframe_interval),
            "-keyint_min",
            str(keyframe_interval),
            "-bf",
            "0",
            "-sc_threshold",
            "0",
            "-force_key_frames",
            f"expr:gte(t,n_forced*{settings.hls_time_seconds})",
            "-x264-params",
            f"keyint={keyframe_interval}:min-keyint={keyframe_interval}:scenecut=0:force-cfr=1",
        ])

    add_audio_options(command)

    command.extend([
        "-max_muxing_queue_size",
        "1024",
        "-f",
        "hls",
        "-hls_time",
        str(settings.hls_time_seconds),
        "-hls_list_size",
        str(settings.hls_list_size),
        "-hls_segment_type",
        "mpegts",
        "-hls_flags",
        "delete_segments+omit_endlist+independent_segments+temp_file",
        "-hls_allow_cache",
        "0",
        "-hls_segment_filename",
        str(segment_path),
        str(playlist_path),
    ])

    return command


def get_video_mode() -> str:
    if settings.video_mode is not None:
        return settings.video_mode

    if settings.transcode_video:
        return "h264"

    return "copy"


def build_video_filter(fps: int) -> str:
    filters = [f"fps={fps}"]

    if settings.transcode_max_width > 0:
        filters.append(f"scale='min({settings.transcode_max_width},iw)':-2")

    filters.append("format=yuv420p")
    return ",".join(filters)


def add_audio_options(command: list[str]) -> None:
    if settings.audio_mode == "none":
        command.append("-an")
        return

    if settings.audio_mode == "copy":
        command.extend(["-c:a", "copy"])
        return

    command.extend([
        "-c:a",
        "aac",
        "-b:a",
        settings.audio_bitrate,
        "-ac",
        str(settings.audio_channels),
        "-ar",
        str(settings.audio_sample_rate),
    ])


async def release_session(session: CameraSession) -> None:
    async with shared_streams_lock:
        stream = shared_streams.get(session.stream_key)

        if stream is None:
            return

        stream.viewer_session_ids.discard(session.id)
        viewer_count = len(stream.viewer_session_ids)

        if viewer_count == 0:
            stream.last_viewer_left_at = datetime.now(timezone.utc)

        logger.info(
            "Detached camera session[%s] from shared stream[%s], viewers=%s",
            session.id,
            stream.id,
            viewer_count,
        )


async def cleanup_idle_streams() -> None:
    now = datetime.now(timezone.utc)
    idle_timeout_seconds = settings.stream_idle_timeout_seconds

    async with shared_streams_lock:
        for stream_key, stream in list(shared_streams.items()):
            if stream.viewer_session_ids:
                continue

            if stream.last_viewer_left_at is None:
                stream.last_viewer_left_at = now
                continue

            idle_seconds = (now - stream.last_viewer_left_at).total_seconds()

            if idle_seconds < idle_timeout_seconds:
                continue

            shared_streams.pop(stream_key, None)
            logger.info("Stopping idle shared stream[%s] after %.1fs", stream.id, idle_seconds)
            await stop_stream_process(stream)
            remove_stream_dir(stream)


async def wait_for_file(path: Path) -> None:
    deadline = asyncio.get_running_loop().time() + settings.hls_start_timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return

        await asyncio.sleep(0.2)


def is_stream_process_running(stream: SharedCameraStream) -> bool:
    return stream.process is not None and stream.process.returncode is None


async def stop_stream_process(stream: SharedCameraStream) -> None:
    process = stream.process
    stream.process = None

    if process is None:
        return

    await stop_process(process)


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout=settings.stop_timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def log_ffmpeg_stderr(stream_id: str, process: asyncio.subprocess.Process) -> None:
    if process.stderr is None:
        return

    while True:
        line = await process.stderr.readline()

        if not line:
            break

        message = line.decode("utf-8", errors="replace").strip()
        if message:
            logger.warning("ffmpeg[%s]: %s", stream_id, message)


async def watch_ffmpeg_process(stream_key: str, stream_id: str, process: asyncio.subprocess.Process) -> None:
    returncode = await process.wait()

    async with shared_streams_lock:
        stream = shared_streams.get(stream_key)

        if stream is not None and stream.id == stream_id and stream.process is process:
            stream.process = None

            if not stream.viewer_session_ids:
                stream.last_viewer_left_at = datetime.now(timezone.utc)

    if returncode == 0:
        logger.info("ffmpeg[%s] exited with code 0", stream_id)
    else:
        logger.warning("ffmpeg[%s] exited with code %s", stream_id, returncode)


def remove_stream_dir(stream: SharedCameraStream) -> None:
    shutil.rmtree(stream.hls_dir, ignore_errors=True)


def build_stream_key(rtsp_url: str, quality: str) -> str:
    parts = [
        rtsp_url.strip(),
        quality,
        get_video_mode(),
        settings.audio_mode,
        str(settings.audio_bitrate),
        str(settings.audio_sample_rate),
        str(settings.audio_channels),
        str(settings.rtsp_transport),
        str(settings.hls_time_seconds),
        str(settings.hls_list_size),
        str(settings.transcode_fps),
        str(settings.transcode_crf),
        str(settings.transcode_max_width),
        str(settings.transcode_preset),
        str(settings.transcode_profile),
        str(settings.transcode_level),
    ]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def is_allowed_hls_filename(filename: str) -> bool:
    if filename == "index.m3u8":
        return True

    return filename.startswith("segment_") and filename.endswith(".ts")


def get_hls_media_type(filename: str) -> str:
    if filename.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"

    if filename.endswith(".ts"):
        return "video/mp2t"

    return "application/octet-stream"


def run() -> None:
    uvicorn.run(
        "cmnc_camera_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    run()
