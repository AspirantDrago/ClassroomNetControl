from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-auth-service"
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = False

    stub_user_id: int = 1
    stub_login: str = "admin"
    stub_role: str = "admin"

    model_config = SettingsConfigDict(
        env_prefix="CMNC_AUTH_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()