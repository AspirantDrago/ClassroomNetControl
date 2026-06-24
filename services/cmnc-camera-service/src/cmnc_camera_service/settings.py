from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-camera-service"
    host: str = "0.0.0.0"
    port: int = 8005

    session_ttl_seconds: int = Field(default=3600, ge=60)
    cleanup_interval_seconds: int = Field(default=60, ge=10)

    ffmpeg_path: str = "ffmpeg"
    rtsp_transport: str = "tcp"
    stop_timeout_seconds: float = Field(default=5.0, ge=1.0)

    hls_root_dir: str = "/tmp/cmnc-camera-hls"
    hls_time_seconds: int = Field(default=2, ge=1)
    hls_list_size: int = Field(default=6, ge=3)
    hls_start_timeout_seconds: float = Field(default=20.0, ge=1.0)

    # Video modes:
    # - h264: browser-safe H.264 HLS. Recommended for Chrome/Edge/Firefox.
    # - copy: keep the camera video codec as-is. Allows H.265 for VLC/Safari-like clients,
    #         but usually will not play through hls.js in Chrome/Edge.
    # - hevc: transcode to H.265. Mostly useful for VLC/Safari-like clients, not hls.js.
    video_mode: Literal["h264", "copy", "hevc"] | None = None

    # Backward-compatible switch. Used only when video_mode is not set.
    # true -> h264, false -> copy.
    transcode_video: bool = True

    # Used for h264/hevc modes. Normalizes broken/missing RTSP timestamps and
    # prevents encoders from seeing an unrealistically high input frame rate.
    transcode_fps: int = Field(default=25, ge=1, le=60)
    transcode_crf: int = Field(default=20, ge=16, le=35)
    transcode_max_width: int = Field(default=0, ge=0)
    transcode_preset: str = "veryfast"

    # H.264 defaults are quality-oriented but still browser-compatible.
    transcode_profile: str = "high"
    transcode_level: str = "5.1"

    # Audio modes:
    # - aac: browser-safe audio for HLS. Recommended.
    # - copy: keep the camera audio codec as-is. May break browser playback.
    # - none: remove audio.
    audio_mode: Literal["aac", "copy", "none"] = "aac"
    audio_bitrate: str = "128k"
    audio_sample_rate: int = Field(default=48000, ge=8000, le=192000)
    audio_channels: int = Field(default=2, ge=1, le=8)

    model_config = SettingsConfigDict(
        env_prefix="CMNC_CAMERA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
