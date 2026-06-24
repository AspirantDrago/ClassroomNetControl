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

    # Used only when transcode_video=true. Normalizes broken/missing RTSP timestamps
    # and prevents libx264 from seeing an unrealistically high input frame rate.
    transcode_fps: int = Field(default=15, ge=1, le=60)
    transcode_crf: int = Field(default=23, ge=18, le=35)
    transcode_max_width: int = Field(default=1280, ge=0)
    transcode_preset: str = "veryfast"
    transcode_profile: str = "baseline"
    transcode_level: str = "4.1"

    # True means ffmpeg always emits browser-safe H.264/yuv420p HLS.
    # False copies the camera video stream and works only when the camera already emits browser-supported H.264.
    transcode_video: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CMNC_CAMERA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
