import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from cmnc_camera_service.schemas import (
    CameraSessionCreateRequest,
    CameraSessionResponse,
    CameraSessionStopResponse,
    HealthResponse,
)
from cmnc_camera_service.session_store import CameraSessionStore
from cmnc_camera_service.settings import settings

session_store = CameraSessionStore(ttl_seconds=settings.session_ttl_seconds)


async def cleanup_expired_sessions() -> None:
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        session_store.delete_expired()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cleanup_task = asyncio.create_task(cleanup_expired_sessions())

    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


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

    session = session_store.create(
        rtsp_url=rtsp_url,
        quality=payload.quality,
    )

    return CameraSessionResponse(
        session_id=session.id,
        mode="fmp4",
        quality=session.quality,
        stream_path=f"/internal/camera/sessions/{session.id}/stream.mp4",
        expires_in_seconds=settings.session_ttl_seconds,
    )


@app.post(
    "/internal/camera/sessions/{session_id}/stop",
    response_model=CameraSessionStopResponse,
)
async def stop_camera_session(session_id: str) -> CameraSessionStopResponse:
    stopped = session_store.delete(session_id)

    return CameraSessionStopResponse(
        stopped=stopped,
        session_id=session_id,
    )


@app.get("/internal/camera/sessions/{session_id}/stream.mp4")
async def stream_camera_session(session_id: str) -> StreamingResponse:
    session = session_store.get(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Camera session not found")

    process = await asyncio.create_subprocess_exec(
        *build_ffmpeg_command(session.rtsp_url),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    if process.stdout is None:
        await stop_process(process)
        raise HTTPException(status_code=502, detail="Could not start ffmpeg stream")

    async def iterator() -> AsyncIterator[bytes]:
        try:
            while True:
                chunk = await process.stdout.read(settings.stream_chunk_size)

                if not chunk:
                    break

                yield chunk
        finally:
            await stop_process(process)

    return StreamingResponse(
        iterator(),
        media_type="video/mp4",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


def build_ffmpeg_command(rtsp_url: str) -> list[str]:
    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        settings.rtsp_transport,
        "-i",
        rtsp_url,
        "-an",
    ]

    if settings.transcode_video:
        command.extend([
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
        ])
    else:
        command.extend(["-c:v", "copy"])

    command.extend([
        "-movflags",
        "frag_keyframe+empty_moov+default_base_moof",
        "-f",
        "mp4",
        "pipe:1",
    ])

    return command


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout=settings.stop_timeout_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


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
