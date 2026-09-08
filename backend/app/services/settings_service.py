"""Runtime configuration overrides on top of app/config.py.

SETTINGS_REGISTRY is the sole validation boundary for anything arriving over
HTTP. A key absent from it is rejected on write and ignored on hydrate, so a
stale row can never resurrect a retired setting.

Applied by setattr onto the `settings` singleton, because every consumer
already reads its value at call time through `settings.X`. That keeps all five
existing read sites (task_routing_gate, rag.gating, auth.security,
appointment_service, email_service) byte-for-byte unchanged.

# ponytail: process-local cache; a second uvicorn worker would not see another
# worker's write until restart. Add pub/sub invalidation if we ever run >1.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.app_setting import AppSetting
from app.models.user import User
from app.services import audit_service


class SettingsValidationError(Exception):
    """Raised when a submitted key or value fails registry validation."""


@dataclass(frozen=True)
class SettingSpec:
    type: type
    group: str
    label: str
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    editable: bool = True


SETTINGS_REGISTRY: dict[str, SettingSpec] = {
    # General
    "clinic_open_hour": SettingSpec(
        int,
        "General",
        "Clinic opens",
        "Hour the calendar grid and slot suggestions start from.",
        minimum=0,
        maximum=23,
    ),
    "clinic_close_hour": SettingSpec(
        int,
        "General",
        "Clinic closes",
        "Must be later than the opening hour.",
        minimum=0,
        maximum=23,
    ),
    "default_appointment_duration_minutes": SettingSpec(
        int,
        "General",
        "Default appointment length",
        "Used when a booking does not specify one.",
        minimum=5,
        maximum=240,
    ),
    "synthetic_only": SettingSpec(
        bool,
        "General",
        "Synthetic data only",
        "Read-only. Set by environment; production refuses to start when true.",
        editable=False,
    ),
    # Security
    "jwt_access_token_expire_minutes": SettingSpec(
        int,
        "Security",
        "Session length (minutes)",
        "Applies to tokens minted after the change. Existing sessions keep their original expiry.",
        minimum=5,
        maximum=1440,
    ),
    "login_rate_limit": SettingSpec(
        str,
        "Security",
        "Login rate limit",
        "Read-only. Applied by a decorator evaluated at import time, so a stored value would "
        "never take effect. Change it in .env and restart.",
        editable=False,
    ),
    # Approval tiers
    "task_routing_auto_threshold": SettingSpec(
        float,
        "Approval tiers",
        "Auto-route above",
        "Confidence at or above which a task routes with no human review. Lowering this means "
        "more work proceeds unreviewed.",
        minimum=0.0,
        maximum=1.0,
    ),
    "task_routing_floor": SettingSpec(
        float,
        "Approval tiers",
        "Human review below",
        "Below this, a task always goes to a human. Must not exceed the auto-route threshold.",
        minimum=0.0,
        maximum=1.0,
    ),
    "email_auto_send_enabled": SettingSpec(
        bool,
        "Approval tiers",
        "Allow automatic replies",
        "Master switch. Off means every drafted reply waits for human approval, whatever the "
        "confidence.",
    ),
    "email_no_autosend_categories": SettingSpec(
        list,
        "Approval tiers",
        "Categories needing grounded, approved replies",
        "These never auto-send AND their replies must be grounded in retrieved records. "
        "Editing this moves both behaviours.",
    ),
    "sufficiency_floor": SettingSpec(
        float,
        "Approval tiers",
        "RAG sufficiency floor",
        "Read-only. Calibrated at 0.44 against nomic-embed-text; recalibrate in code if the "
        "embedding provider changes.",
        editable=False,
    ),
    # Routing rules
    "task_routing_category_roles": SettingSpec(
        dict,
        "Routing rules",
        "Category to role overrides",
        "Only categories you change are stored; the rest fall through to the built-in table.",
    ),
    # Integrations
    "outlook_poll_interval_seconds": SettingSpec(
        int,
        "Integrations",
        "Mailbox poll interval (seconds)",
        "Takes effect on the next poll, no restart needed.",
        minimum=15,
        maximum=3600,
    ),
    "outlook_max_messages_per_poll": SettingSpec(
        int,
        "Integrations",
        "Messages per poll",
        minimum=1,
        maximum=100,
    ),
    "outlook_enabled": SettingSpec(
        bool,
        "Integrations",
        "Outlook connector",
        "Read-only. Enabling needs a token cache file written by scripts/outlook_login.py.",
        editable=False,
    ),
    "outlook_mailbox_address": SettingSpec(
        str,
        "Integrations",
        "Mailbox",
        "Read-only.",
        editable=False,
    ),
    # Model configuration
    "llm_model": SettingSpec(str, "Model", "Model", "Ollama model tag."),
    "llm_temperature": SettingSpec(
        float,
        "Model",
        "Temperature",
        "Affects every LLM call including triage classification. Above about 0.6 classification "
        "becomes unreliable, so the range is capped.",
        minimum=0.0,
        maximum=0.6,
    ),
    "llm_max_tokens": SettingSpec(int, "Model", "Max tokens", minimum=256, maximum=8192),
    "llm_timeout_seconds": SettingSpec(int, "Model", "Timeout (seconds)", minimum=5, maximum=300),
}

# Captured at import, BEFORE any hydrate() call mutates the singleton. This is
# what "reset to default" restores and what the API reports as the default.
ENV_DEFAULTS: dict[str, Any] = {key: getattr(settings, key) for key in SETTINGS_REGISTRY}

_LLM_KEYS = {"llm_model", "llm_temperature", "llm_max_tokens", "llm_timeout_seconds"}


def _coerce(key: str, spec: SettingSpec, value: Any) -> Any:
    if spec.type is bool:
        if not isinstance(value, bool):
            raise SettingsValidationError(f"{key} must be true or false")
        return value
    if spec.type in (int, float):
        # bool is a subclass of int; reject it explicitly so True is not 1.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsValidationError(f"{key} must be a number")
        value = spec.type(value)
        if spec.minimum is not None and value < spec.minimum:
            raise SettingsValidationError(f"{key} must be at least {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise SettingsValidationError(f"{key} must be at most {spec.maximum}")
        return value
    if spec.type is str:
        if not isinstance(value, str):
            raise SettingsValidationError(f"{key} must be text")
        return value
    if spec.type is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise SettingsValidationError(f"{key} must be a list of strings")
        return value
    if spec.type is dict:
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise SettingsValidationError(f"{key} must be an object of string to string")
        return value
    raise SettingsValidationError(f"{key} has an unsupported type")


def _check_cross_field(pending: dict[str, Any]) -> None:
    """Rules spanning two keys, which a per-key spec cannot express.

    Reads the pending value if present, otherwise the current live value, so a
    request that changes only one half of a pair is still checked against the
    other.
    """

    def effective(key: str) -> Any:
        return pending[key] if key in pending else getattr(settings, key)

    if effective("clinic_close_hour") <= effective("clinic_open_hour"):
        raise SettingsValidationError("Closing hour must be later than opening hour")
    if effective("task_routing_floor") > effective("task_routing_auto_threshold"):
        raise SettingsValidationError(
            "Human review threshold must not exceed the auto-route threshold"
        )


def validate(values: dict[str, Any]) -> dict[str, Any]:
    """Validate a whole batch. Raises before anything is written."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        spec = SETTINGS_REGISTRY.get(key)
        if spec is None:
            raise SettingsValidationError(f"Unknown setting '{key}'")
        if not spec.editable:
            raise SettingsValidationError(f"'{key}' is read-only")
        cleaned[key] = _coerce(key, spec, value)
    _check_cross_field(cleaned)
    return cleaned


def _apply(key: str, value: Any) -> None:
    setattr(settings, key, value)


async def hydrate(db: AsyncSession) -> None:
    """Load stored overrides onto the settings singleton.

    Called at startup and after every write. Rows whose key is no longer in the
    registry are skipped rather than raising, so removing a setting from the
    registry cannot break boot.
    """
    rows = (await db.execute(select(AppSetting))).scalars().all()
    for row in rows:
        if row.key in SETTINGS_REGISTRY:
            _apply(row.key, row.value["v"])
    _clear_llm_cache_if_needed({row.key for row in rows})


def _clear_llm_cache_if_needed(changed: set[str]) -> None:
    # get_llm() is lru_cache'd, so a model or temperature change would not be
    # picked up until restart without this.
    if changed & _LLM_KEYS:
        from app.llm.provider import get_llm

        get_llm.cache_clear()


async def set_settings(db: AsyncSession, values: dict[str, Any], actor: User) -> dict[str, Any]:
    """Validate, persist, audit and apply a batch of settings.

    All or nothing: one bad key rejects the whole request before any write.
    """
    cleaned = validate(values)

    for key, value in cleaned.items():
        old = getattr(settings, key)
        row = await db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value={"v": value}, updated_by=actor.id))
        else:
            row.value = {"v": value}
            row.updated_by = actor.id
        await audit_service.record_event(
            db,
            action="settings.update",
            actor=actor,
            details={"key": key, "old": old, "new": value},
        )

    await db.commit()
    for key, value in cleaned.items():
        _apply(key, value)
    _clear_llm_cache_if_needed(set(cleaned))
    return cleaned
