from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-mikrotik-poller-service"

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"
    inventory_service_url: str = "http://localhost:8003"

    mikrotik_verify_tls: bool = False
    mikrotik_timeout_seconds: float = 10.0

    supervisor_interval_seconds: float = 10.0
    publish_empty_snapshots: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CMNC_MIKROTIK_POLLER_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
