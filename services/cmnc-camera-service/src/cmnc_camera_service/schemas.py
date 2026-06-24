from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    service: str
    status: str


class CameraSessionCreateRequest(BaseModel):
    rtsp_url: str = Field(min_length=1, max_length=4096)
    quality: str = Field(pattern="^(main|sub)$")


class CameraSessionResponse(BaseModel):
    session_id: str
    mode: str
    quality: str
    stream_path: str
    expires_in_seconds: int


class CameraSessionStopResponse(BaseModel):
    stopped: bool
    session_id: str
