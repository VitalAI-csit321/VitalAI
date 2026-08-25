from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    app_name: str = "VitalAI"
    app_version: str = "0.1.0"
    synthetic_only: bool = True

    # CORS — comma-separated origins allowed to call this API from a browser.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Database — required; populated from DATABASE_URL env var or .env file.
    # Empty string default only exists so mypy does not flag Settings() as
    # missing a required argument; the validator below rejects a missing value.
    database_url: str = Field(default="")
    jwt_secret_key: str = Field(default="")

    # Auth
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    login_rate_limit: str = "5/minute"

    # LLM
    llm_provider: str = "ollama"
    llm_model: str = "gemma2:9b"
    ollama_base_url: str = "http://ollama:11434"

    # Call transcription (Phase 1 MVP — local STT, no Twilio yet)
    whisper_model: str = "base"

    # Bedrock
    aws_region: str = "ap-southeast-2"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"

    # Cache
    redis_url: str = "redis://redis:6379/0"

    # Object storage
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "clinical-documents"

    # Embeddings
    embedding_provider: str = "nomic"  # nomic (dev) | bedrock (prod)
    embedding_model: str = "nomic-embed-text"

    # RAG gating (FR-RAG-02 / FR-RAG-03)
    # 0.44 is calibrated against nomic-embed-text (512-dim truncated) top_score on
    # real ingested chunks, not a guess: 5-patient calibration found easy-negative
    # (off-domain) queries top out at 0.43, true-positive natural-language questions
    # start at 0.4814; 0.50 sat inside that positive range and rejected legitimate
    # questions (e.g. broad phrasing like "tell me about this patient" scored 0.4933).
    # Recalibrate if embedding_provider changes; the old 0.50/0.75 pair predates any
    # such measurement.
    sufficiency_floor: float = 0.44
    confidence_threshold: float = 0.75
    confidence_source: str = "retrieval_similarity"

    # Task routing gate (FR-GOV-02), separate from the RAG gate above:
    # gates task-routing classification confidence, not RAG grounding.
    task_routing_auto_threshold: float = 0.90
    task_routing_floor: float = 0.70

    # Outlook connector (inbound mail via Microsoft Graph).
    # Defaults to disabled: every existing test, every other worktree, and CI
    # run with the connector inert, so nothing here can reach a real mailbox
    # unless an operator explicitly turns it on in that environment's .env.
    # Enabling it also disables auto-send in email_service.draft_reply(), so a
    # drafted reply only leaves the building after a human approves it.
    outlook_enabled: bool = False
    outlook_client_id: str = ""
    # /consumers = personal Microsoft accounts. A work/school tenant would use
    # https://login.microsoftonline.com/<tenant-id> instead.
    outlook_authority: str = "https://login.microsoftonline.com/consumers"
    # Written by scripts/outlook_login.py, read by outlook_auth.get_access_token().
    # Holds a live refresh token: gitignored, never commit it.
    outlook_token_cache_path: str = ".outlook_token_cache.json"
    outlook_poll_interval_seconds: int = 60
    outlook_max_messages_per_poll: int = 25
    # The mailbox this connector reads. Used as the fallback recipient when a
    # message arrives with toRecipients absent, which happens for mail sent to
    # a shared mailbox.
    outlook_mailbox_address: str = ""

    @model_validator(mode="after")
    def _require_runtime_secrets(self) -> "Settings":
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")
        if not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY must be set")
        if self.outlook_enabled and not self.outlook_client_id:
            raise ValueError("OUTLOOK_CLIENT_ID must be set when OUTLOOK_ENABLED=true")
        return self


settings = Settings()
