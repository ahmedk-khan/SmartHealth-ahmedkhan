from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = Field(default="sqlite+pysqlite:///./app.db", alias="DATABASE_URL")
    jwt_secret: str = Field(default="change-me-locally", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    temporal_host: str = Field(default="localhost:7233", alias="TEMPORAL_HOST")
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(default="app-workflow", alias="TEMPORAL_TASK_QUEUE")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND")
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    kafka_enabled: bool = Field(default=False, alias="KAFKA_ENABLED")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_prefix: str = Field(default="app", alias="KAFKA_TOPIC_PREFIX")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
