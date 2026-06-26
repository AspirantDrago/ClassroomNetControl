from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-policy-sync-service"

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"
    classroom_service_url: str = "http://localhost:8002"
    inventory_service_url: str = "http://localhost:8003"
    wan_policy_changed_queue: str = "cmnc.policy_sync.wan_policy_changed"

    address_list_name: str = Field(
        default="cmnc_wan_blocked",
        validation_alias="CMNC_POLICY_SYNC_ADDRESS_LIST_NAME",
    )

    mikrotik_verify_tls: bool = Field(
        default=False,
        validation_alias="CMNC_MIKROTIK_VERIFY_TLS",
    )
    mikrotik_timeout_seconds: float = 10.0

    supervisor_interval_seconds: float = 10.0
    reconcile_interval_seconds: float = 30.0
    router_event_queue_max_size: int = 1000

    managed_comment_prefix: str = "managed-by=cmnc;"
    kill_connections_on_block: bool = True

    healthcheck_write_probe_enabled: bool = Field(
        default=True,
        validation_alias="CMNC_POLICY_SYNC_HEALTHCHECK_WRITE_PROBE_ENABLED",
    )
    healthcheck_address_list_name: str = Field(
        default="cmnc_healthcheck",
        validation_alias="CMNC_POLICY_SYNC_HEALTHCHECK_ADDRESS_LIST_NAME",
    )
    healthcheck_address: str = Field(
        default="198.51.100.254",
        validation_alias="CMNC_POLICY_SYNC_HEALTHCHECK_ADDRESS",
    )
    healthcheck_connection_src_ip: str = Field(
        default="127.0.0.1",
        validation_alias="CMNC_POLICY_SYNC_HEALTHCHECK_CONNECTION_SRC_IP",
    )

    model_config = SettingsConfigDict(
        env_prefix="CMNC_POLICY_SYNC_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
