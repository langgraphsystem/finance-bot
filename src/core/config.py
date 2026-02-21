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

    # Supabase MCP (optional)
    supabase_access_token: str = ""
    supabase_project_ref: str = ""

    @property
    def mcp_project_ref(self) -> str:
        """Return project ref — explicit setting or extracted from supabase_url."""
        if self.supabase_project_ref:
            return self.supabase_project_ref
        # Extract from https://<ref>.supabase.co
        if self.supabase_url:
            host = self.supabase_url.split("//")[-1].split(".")[0]
            if host and host != "supabase":
                return host
        return ""

    @property
    def async_database_url(self) -> str:
        """Return database URL with asyncpg driver for SQLAlchemy async."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

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

    # Composio (Gmail + Calendar integration)
    composio_api_key: str = ""

    # Google OAuth (legacy — replaced by Composio)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    oauth_encryption_key: str = ""

    # Google Maps API
    google_maps_api_key: str = ""

    # YouTube Data API v3
    youtube_api_key: str = ""

    # Mem0
    mem0_api_key: str = ""
    mem0_base_url: str = ""

    # Slack (Phase 4)
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # WhatsApp Business Cloud API (Phase 4)
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    # Twilio SMS (Phase 4)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Stripe (Phase 4)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""

    # E2B (code sandbox execution)
    e2b_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    rate_limit_per_minute: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
