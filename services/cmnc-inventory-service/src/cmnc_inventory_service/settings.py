from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-inventory-service"
    host: str = "0.0.0.0"
    port: int = 8003

    database_url: str = (
        "postgresql+asyncpg://cmnc:cmnc_password@localhost:5432/cmnc_inventory"
    )
    db_echo: bool = False

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"
    dhcp_leases_observed_queue: str = "cmnc.inventory.dhcp_leases_observed"

    model_config = SettingsConfigDict(
        env_prefix="CMNC_INVENTORY_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
