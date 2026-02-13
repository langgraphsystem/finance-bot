from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    telegram_webhook_url: str = ""

    # Database
    database_url: str
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_service_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_ai_api_key: str = ""

    # Langfuse
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # Mem0
    mem0_api_key: str = ""
    mem0_base_url: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    rate_limit_per_minute: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
