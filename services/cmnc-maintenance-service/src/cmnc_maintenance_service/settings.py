from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-maintenance-service"
    host: str = "0.0.0.0"
    port: int = 8004

    docker_socket_path: str = "/var/run/docker.sock"
    container_name_prefix: str = "cmnc-"
    docker_request_timeout_seconds: float = 5.0

    postgres_container_name: str = "cmnc-postgres"
    postgres_databases: str = "cmnc_auth,cmnc_classroom,cmnc_inventory,cmnc_policy_sync"
    postgres_user: str = "cmnc"
    postgres_restore_dir: str = "/tmp"

    @property
    def postgres_database_names(self) -> list[str]:
        return [
            name.strip()
            for name in self.postgres_databases.split(",")
            if name.strip()
        ]

    model_config = SettingsConfigDict(
        env_prefix="CMNC_MAINTENANCE_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
