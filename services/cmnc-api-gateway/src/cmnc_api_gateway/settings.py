from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-api-gateway"
    host: str = "0.0.0.0"
    port: int = 8000

    auth_service_url: str = "http://localhost:8001"
    classroom_service_url: str = "http://localhost:8002"
    inventory_service_url: str = "http://localhost:8003"

    default_router_id: int = 1

    model_config = SettingsConfigDict(
        env_prefix="CMNC_API_GATEWAY_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
