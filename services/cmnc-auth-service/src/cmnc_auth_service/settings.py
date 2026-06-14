from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "cmnc-auth-service"
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = False

    database_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    bootstrap_superadmin_username: str = "superadmin"
    bootstrap_superadmin_password: str | None = None
    bootstrap_superadmin_display_name: str = "Super Administrator"

    model_config = SettingsConfigDict(
        env_prefix="CMNC_AUTH_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()