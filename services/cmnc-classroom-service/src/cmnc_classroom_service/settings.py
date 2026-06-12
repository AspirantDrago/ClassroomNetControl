from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-classroom-service"
    host: str = "0.0.0.0"
    port: int = 8002

    database_url: str = (
        "postgresql+asyncpg://cmnc:cmnc_password@localhost:5432/cmnc"
    )
    db_echo: bool = False

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"

    policy_sync_completed_queue: str = "cmnc.classroom.policy_sync_completed"
    policy_sync_failed_queue: str = "cmnc.classroom.policy_sync_failed"

    default_router_id: int = 1
    managed_address_list_name: str = "cmnc_wan_blocked"

    seed_demo_data: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CMNC_CLASSROOM_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()