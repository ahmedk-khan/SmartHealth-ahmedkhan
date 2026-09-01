from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator


class Settings(BaseSettings):
    app_env: str = "local"
    build_revision: str = Field(default="development", alias="BUILD_REVISION")
    log_level: str = "INFO"
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, ge=1, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, ge=0, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, ge=1, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, ge=0, alias="DB_POOL_RECYCLE")
    jwt_secret: str = Field(default="change-me-locally", alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    temporal_host: str = Field(default="localhost:7233", alias="TEMPORAL_HOST")
    temporal_namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    temporal_task_queue: str = Field(default="app-workflow", alias="TEMPORAL_TASK_QUEUE")
    temporal_workflow_timeout_minutes: int = Field(default=30, ge=1, le=1440, alias="TEMPORAL_WORKFLOW_TIMEOUT_MINUTES")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    cors_allowed_origins: list[str] = Field(default_factory=list, alias="CORS_ALLOWED_ORIGINS")
    auth_login_rate_limit: str = Field(default="5/minute", alias="AUTH_LOGIN_RATE_LIMIT")
    auth_register_rate_limit: str = Field(default="3/hour", alias="AUTH_REGISTER_RATE_LIMIT")
    auth_password_reset_rate_limit: str = Field(default="3/hour", alias="AUTH_PASSWORD_RESET_RATE_LIMIT")
    celery_broker_url: str = Field(default="redis://localhost:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/2", alias="CELERY_RESULT_BACKEND")
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    billing_force_failure: bool = Field(default=False, alias="BILLING_FORCE_FAILURE")
    kafka_enabled: bool = Field(default=False, alias="KAFKA_ENABLED")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_consumer_group: str = Field(default="app-analytics", alias="KAFKA_CONSUMER_GROUP")
    kafka_topic_prefix: str = Field(default="app", alias="KAFKA_TOPIC_PREFIX")
    embedding_provider: str = Field(default="huggingface", alias="EMBEDDING_PROVIDER")
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_model: str = Field(default="microsoft/harrier-oss-v1-0.6b", alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1024, alias="EMBEDDING_DIMENSIONS")
    embedding_batch_size: int = Field(default=32, ge=1, alias="EMBEDDING_BATCH_SIZE")
    retrieval_top_k: int = Field(default=5, alias="RETRIEVAL_TOP_K")
    retrieval_min_similarity: float = Field(default=0.60, alias="RETRIEVAL_MIN_SIMILARITY")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    ai_conversation_key: str = Field(default="", alias="AI_CONVERSATION_KEY")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    use_fake_llm: bool = Field(default=False, alias="USE_FAKE_LLM")
    llm_timeout_seconds: float = Field(default=60, ge=1, alias="LLM_TIMEOUT_SECONDS")
    ai_rate_limit_per_minute: int = Field(default=30, ge=1, alias="AI_RATE_LIMIT_PER_MINUTE")
    ai_cache_ttl_seconds: int = Field(default=300, ge=1, alias="AI_CACHE_TTL_SECONDS")
    booking_demo_pause_seconds: float = Field(default=0, ge=0, le=300, alias="BOOKING_DEMO_PAUSE_SECONDS")
    async_booking_enabled: bool = Field(default=False, alias="ASYNC_BOOKING_ENABLED")
    booking_workflow_timeout_minutes: int = Field(default=30, ge=1, le=1440, alias="BOOKING_WORKFLOW_TIMEOUT_MINUTES")
    allow_self_service_admin_registration: bool = Field(default=False, alias="ALLOW_SELF_SERVICE_ADMIN_REGISTRATION")

    @model_validator(mode="after")
    def validate_production_security(self):
        environment = self.app_env.lower()
        supported_providers = {"openai", "groq"}
        if self.llm_provider.lower() not in supported_providers:
            raise ValueError(f"Unsupported LLM provider: {self.llm_provider}")
        if not self.cors_allowed_origins and environment in {"local", "test", "development", "dev"}:
            self.cors_allowed_origins = ["http://localhost:3000", "http://localhost:8000"]
        if not self.database_url:
            if environment in {"local", "test", "development", "dev"}:
                self.database_url = "sqlite+pysqlite:///./app.db"
            else:
                raise ValueError("DATABASE_URL must be set outside local, test, and development environments")
        if self.app_env.lower() in {"production", "prod"}:
            known_bad_secrets = {
                "change-me-locally",
                "change-me-in-development",
                "smarthealth-local-demo-secret-change-in-production",
            }
            if self.jwt_secret in known_bad_secrets or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be a unique secret of at least 32 characters in production")
            if not self.llm_api_key.strip():
                raise ValueError("LLM_API_KEY must be set in production")
        return self

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
