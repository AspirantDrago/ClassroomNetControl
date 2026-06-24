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
    stream_chunk_size: int = Field(default=65536, ge=4096)
    stop_timeout_seconds: float = Field(default=5.0, ge=1.0)

    # False means ffmpeg copies the camera video stream into fragmented MP4.
    # This is light on CPU, but browser playback requires a browser-supported codec, usually H.264.
    # Set to true only if cameras need transcoding and the server CPU can handle it.
    transcode_video: bool = False

    model_config = SettingsConfigDict(
        env_prefix="CMNC_CAMERA_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
