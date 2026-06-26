from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-api-gateway"
    host: str = "0.0.0.0"
    port: int = 8000

    auth_service_url: str = "http://localhost:8001"
    classroom_service_url: str = "http://localhost:8002"
    inventory_service_url: str = "http://localhost:8003"
    mikrotik_poller_service_url: str = "http://localhost:8006"
    policy_sync_service_url: str = "http://localhost:8007"
    maintenance_service_url: str = "http://localhost:8004"
    camera_service_url: str = "http://localhost:8005"

    default_router_id: int = 1

    model_config = SettingsConfigDict(
        env_prefix="CMNC_API_GATEWAY_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
