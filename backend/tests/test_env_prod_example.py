"""The expo box's .env starts as a copy of .env.prod.example. Settings ignores
unknown keys, so a misspelled flag there would silently do nothing."""

from pathlib import Path

from app.config import Settings

TEMPLATE = Path(__file__).resolve().parents[1] / ".env.prod.example"
# Read by docker-compose.prod.yml for interpolation, not by the app.
COMPOSE_ONLY = {"SITE_ADDRESS", "POSTGRES_PASSWORD"}


def _values() -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in TEMPLATE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return {key.strip(): value.strip() for key, value in pairs}


def test_every_key_is_read_by_the_app_or_by_compose():
    known = {name.upper() for name in Settings.model_fields} | COMPOSE_ONLY
    assert set(_values()) - known == set()


def test_links_in_emails_point_at_the_public_site():
    # Form and password-reset links are built from the first CORS origin.
    values = _values()
    assert values["CORS_ORIGINS"].split(",")[0] == f"https://{values['SITE_ADDRESS']}"


def test_the_template_never_claims_production():
    # main.py refuses APP_ENV=production with synthetic data.
    values = _values()
    assert values["APP_ENV"] != "production"
    assert values["SYNTHETIC_ONLY"] == "true"
