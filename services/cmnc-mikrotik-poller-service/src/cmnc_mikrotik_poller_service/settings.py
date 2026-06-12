from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-mikrotik-poller-service"

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"

    router_id: int = 1

    mikrotik_base_url: str = "http://192.168.0.1/rest"
    mikrotik_username: str = "admin"
    mikrotik_password: SecretStr = SecretStr("admin")

    mikrotik_verify_tls: bool = False
    mikrotik_timeout_seconds: float = 10.0

    poll_interval_seconds: float = 5.0
    publish_empty_snapshots: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CMNC_MIKROTIK_POLLER_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()