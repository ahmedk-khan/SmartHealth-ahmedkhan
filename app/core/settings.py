from pydantic import AnyUrl, BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: AnyUrl = "sqlite+pysqlite:///./app.db"
    jwt_secret: str = "change-me-locally"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
