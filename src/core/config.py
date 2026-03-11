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

    @property
    def public_base_url(self) -> str:
        """Infer the public app base URL from configured callbacks/webhook."""
        if self.google_redirect_uri:
            return self.google_redirect_uri.rsplit("/oauth/", 1)[0]
        if self.telegram_webhook_url:
            return self.telegram_webhook_url.rsplit("/", 1)[0]
        return ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_computer_use_model: str = "gemini-3.1-flash-lite-preview"
    google_ai_api_key: str = ""
    xai_api_key: str = ""
    grok_dual_search_model: str = "grok-4.20-experimental-beta-0304-reasoning"

    # Langfuse
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # Composio (Gmail + Calendar + Sheets integration)
    composio_api_key: str = ""
    composio_gmail_auth_config_id: str = ""
    composio_calendar_auth_config_id: str = ""
    composio_sheets_auth_config_id: str = ""

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
    whatsapp_app_secret: str = ""

    # Twilio SMS (Phase 4)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # Voice / telephony
    voice_public_base_url: str = ""
    voice_ws_base_url: str = ""
    voice_openai_realtime_model: str = "gpt-realtime-1.5"
    voice_openai_realtime_fallback_model: str = "gpt-realtime-mini"
    voice_openai_realtime_voice: str = "marin"
    voice_default_owner_telegram_id: str = ""
    voice_default_owner_name: str = "the owner"
    voice_default_business_name: str = "our business"
    voice_default_business_hours: str = "business hours unavailable"
    voice_default_services: str = "general assistance"
    voice_verification_ttl_seconds: int = 300
    voice_verification_code_length: int = 6
    voice_enabled: bool = True
    voice_allow_outbound: bool = True
    voice_allow_write_tools: bool = True
    voice_receptionist_only: bool = False
    voice_force_callback_mode: bool = False

    # Stripe (Phase 4)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    stripe_tax_default_code: str = ""
    invoice_tax_cache_ttl_hours: int = 168

    # E2B (code sandbox execution)
    e2b_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    health_secret: str = ""  # When set, /health/detailed requires Authorization: Bearer <token>
    rate_limit_per_minute: int = 30
    ff_locale_v2_read: bool = True
    ff_locale_v2_write: bool = True
    ff_reminder_dispatch_v2: bool = True
    ff_langgraph_checkpointer: bool = False
    ff_langgraph_brief_parallel: bool = True
    ff_langgraph_email_hitl: bool = True
    ff_langgraph_booking: bool = False
    ff_supervisor_routing: bool = False
    ff_reverse_prompting: bool = False
    ff_extended_context: bool = False
    ff_langgraph_document: bool = False
    ff_scheduled_actions: bool = False
    ff_sia_synthesis: bool = False
    ff_dual_search: bool = False
    ff_post_gen_check: bool = True
    ff_browser_computer_use: bool = True
    ff_deep_agents: bool = False
    release_default_cohort: str = "normal"
    release_internal_user_ids: str = ""
    release_trusted_user_ids: str = ""
    release_beta_user_ids: str = ""
    release_vip_user_ids: str = ""
    release_sensitive_roles: str = "accountant,assistant"
    release_rollout_name: str = ""
    release_rollout_percent: int = 0
    release_shadow_mode: bool = False
    release_health_logging: bool = True
    release_health_error_rate_threshold: float = 0.05
    release_health_no_reply_rate_threshold: float = 0.02
    release_health_rate_limited_threshold: float = 0.10
    release_health_shadow_mismatch_threshold: float = 0.20
    release_health_shadow_compare_failure_threshold: float = 0.10

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
