from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_env: str = "development"
    app_name: str = "VitalAI"
    app_version: str = "0.1.0"
    synthetic_only: bool = True

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
    sufficiency_floor: float = 0.50
    confidence_threshold: float = 0.75
    confidence_source: str = "retrieval_similarity"

    # Task routing gate (FR-GOV-02) — separate from the RAG gate above,
    # gates task-routing classification confidence, not RAG grounding.
    task_routing_auto_threshold: float = 0.90
    task_routing_floor: float = 0.70

    @model_validator(mode="after")
    def _require_runtime_secrets(self) -> "Settings":
        if not self.database_url:
            raise ValueError("DATABASE_URL must be set")
        if not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY must be set")
        return self


settings = Settings()
