from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-maintenance-service"
    host: str = "0.0.0.0"
    port: int = 8004

    docker_socket_path: str = "/var/run/docker.sock"
    container_name_prefix: str = "cmnc-"
    docker_request_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_prefix="CMNC_MAINTENANCE_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
