from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-mikrotik-poller-service"
    host: str = "0.0.0.0"
    port: int = 8006

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"
    inventory_service_url: str = "http://localhost:8003"
    mikrotik_timeout_seconds: float = 10.0

    supervisor_interval_seconds: float = 10.0
    publish_empty_snapshots: bool = True
    error_backoff_max_seconds: float = Field(default=120.0, ge=1.0)
    error_backoff_jitter_fraction: float = Field(default=0.1, ge=0.0, le=0.5)
    heartbeat_interval_seconds: float = Field(default=15.0, ge=1.0)

    model_config = SettingsConfigDict(
        env_prefix="CMNC_MIKROTIK_POLLER_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
