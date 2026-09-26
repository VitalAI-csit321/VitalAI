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

    # RAG gating (FR-RAG-02)
    # 0.44 is calibrated against nomic-embed-text (512-dim truncated) top_score on
    # real ingested chunks, not a guess: 5-patient calibration found easy-negative
    # (off-domain) queries top out at 0.43, true-positive natural-language questions
    # start at 0.4814; 0.50 sat inside that positive range and rejected legitimate
    # questions (e.g. broad phrasing like "tell me about this patient" scored 0.4933).
    # Recalibrate if embedding_provider changes.
    sufficiency_floor: float = 0.44

    # Task routing gate (FR-GOV-02), separate from the RAG gate above:
    # gates task-routing classification confidence, not RAG grounding.
    task_routing_auto_threshold: float = 0.90
    task_routing_floor: float = 0.70

    # Clinic hours. The calendar UI renders an 8am-6pm grid; these are the
    # single source of truth so a clinic that opens at 7 needs no code change.
    clinic_open_hour: int = 8
    clinic_close_hour: int = 18
    # The zone those hours are in. Stored timestamps stay UTC-aware; this is
    # only how an instant becomes a clinic day and a clinic day becomes a
    # window. Read-only in settings_service.SETTINGS_REGISTRY: a name that is
    # not a real zone would raise inside zoneinfo on every calendar call.
    clinic_timezone: str = "Australia/Sydney"
    # Public holidays the clinic closes on, as a python-holidays subdivision
    # code for Australia. Read-only like clinic_timezone: both describe where
    # the clinic is. ponytail: public holidays only; add a closed-dates list if
    # the clinic wants ad-hoc closures.
    clinic_holiday_region: str = "NSW"
    # Used when a booking does not specify a duration explicitly.
    default_appointment_duration_minutes: int = 30

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
    # How long an unclaimed provisional patient record is kept before it is
    # anonymised in place (build spec 9.1), and how often the sweep runs.
    provisional_patient_ttl_days: int = 90
    provisional_purge_interval_seconds: int = 86400
    # Appointment reminders (build spec §16). Its own flag, deliberately not
    # agentic_pipeline_enabled: reminders are not part of the agent graph, and
    # a job that emails real patients must not start because someone pulled
    # the branch. Every 15 minutes rather than daily, because "24 hours
    # before" needs finer resolution than a daily job; reminder_sent_at makes
    # the interval affect only how late a reminder can be, never whether it
    # duplicates. Neither is in settings_service.SETTINGS_REGISTRY, for the
    # same reason agentic_pipeline_enabled is not: the sweep only starts in
    # lifespan, so a registered switch would look like it works while doing
    # nothing.
    appointment_reminders_enabled: bool = False
    appointment_reminder_interval_seconds: int = 900
    # How long a medication can go unreviewed before a repeat request needs a
    # review first (spec §12.3). Not in SETTINGS_REGISTRY: it is a clinical
    # policy value, not a runtime switch for an admin to nudge.
    medication_review_interval_days: int = 180
    outlook_max_messages_per_poll: int = 25
    # The mailbox this connector reads. Used as the fallback recipient when a
    # message arrives with toRecipients absent, which happens for mail sent to
    # a shared mailbox.
    outlook_mailbox_address: str = ""

    # LangGraph agent pipeline. Off: today's ingest/draft/approve path runs
    # exactly as before and no checkpointer tables are created.
    agentic_pipeline_enabled: bool = False
    # Multi-turn email conversations on one case: replies linked by their
    # headers, verification requests and the booking flow (appointment request
    # -> details + preferred day -> offered times -> booked). The email half
    # lives in the graph, so it also needs agentic_pipeline_enabled; the call
    # half (a provisional profile from phone + name) needs only this. Its
    # templated emails and the booking itself go out with no human approving
    # them, which is why it is off by default.
    email_booking_conversation_enabled: bool = False

    # LLM generation params. Previously never passed to the provider at all;
    # get_llm() now forwards them, and settings_service clears its lru_cache
    # whenever one changes. Temperature is capped at 0.6 in SETTINGS_REGISTRY
    # because it affects every LLM call including triage classification.
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    # 30s wasn't enough headroom for a cold Ollama model load on a modest
    # dev machine (~30-40s just to reload from disk before generating a
    # token); paired with OLLAMA_KEEP_ALIVE=-1 on the ollama compose service
    # so this only matters once per container start, not once per idle gap.
    llm_timeout_seconds: int = 90

    # Governance kill switch for autonomous outbound email. ANDed into
    # email_service.draft_reply()'s safe_to_send_immediately.
    email_auto_send_enabled: bool = True

    # Overrides for the hardcoded category tables. Empty dict = no override.
    # {task_category_value: user_role_value}
    task_routing_category_roles: dict[str, str] = {}
    # Categories whose replies must be RAG-grounded and never auto-send.
    email_no_autosend_categories: list[str] = [
        "prescription_renewal",
        "results_enquiry",
        "referral_request",
    ]

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
