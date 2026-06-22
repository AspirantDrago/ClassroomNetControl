from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-policy-sync-service"

    rabbitmq_url: str = "amqp://cmnc:cmnc_password@localhost:5672/cmnc"
    classroom_service_url: str = "http://localhost:8002"
    wan_policy_changed_queue: str = "cmnc.policy_sync.wan_policy_changed"
    default_router_id: int = 1

    address_list_name: str = Field(
        default="cmnc_wan_blocked",
        validation_alias="CMNC_POLICY_SYNC_ADDRESS_LIST_NAME",
    )

    mikrotik_base_url: str = Field(
        default="http://192.168.0.1/rest",
        validation_alias="CMNC_MIKROTIK_BASE_URL",
    )
    mikrotik_username: str = Field(
        default="cmnc_service",
        validation_alias="CMNC_MIKROTIK_USERNAME",
    )
    mikrotik_password: SecretStr = Field(
        default=SecretStr("change_me"),
        validation_alias="CMNC_MIKROTIK_PASSWORD",
    )
    mikrotik_verify_tls: bool = Field(
        default=False,
        validation_alias="CMNC_MIKROTIK_VERIFY_TLS",
    )
    mikrotik_timeout_seconds: float = 10.0

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