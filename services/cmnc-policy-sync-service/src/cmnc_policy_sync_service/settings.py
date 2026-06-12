from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-policy-sync-service"

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"

    classroom_service_url: str = "http://localhost:8002"

    wan_policy_changed_queue: str = "cmnc.policy_sync.wan_policy_changed"

    default_router_id: int = 1

    model_config = SettingsConfigDict(
        env_prefix="CMNC_POLICY_SYNC_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
