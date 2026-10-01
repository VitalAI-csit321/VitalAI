"""scripts/deploy.sh: refuse a bad .env before anything starts, and rebuild the
image whenever what it installs changes."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"
TEMPLATE = SCRIPT.parents[1] / ".env.prod.example"


def _deploy(
    *args: str, env_file: Path | None = None, stdin: str = ""
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if env_file is not None:
        env["ENV_FILE"] = str(env_file)
    return subprocess.run(
        ["bash", str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=env
    )


def _env(tmp_path: Path, **changes: str) -> Path:
    """The template, filled the way the expo plan fills it, with changes applied."""
    filled = {
        "POSTGRES_PASSWORD": "pg-secret",
        "JWT_SECRET_KEY": "k" * 64,
        "MINIO_SECRET_KEY": "minio-secret",
    } | changes
    lines = []
    for line in TEMPLATE.read_text().splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={filled[key]}" if "=" in line and key in filled else line)
    path = tmp_path / ".env"
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ("backend/requirements.lock\n", "yes"),
        ("backend/requirements.txt\n", "yes"),
        ("backend/.dockerignore\n", "yes"),
        ("backend/app/main.py\nbackend/Dockerfile\n", "yes"),
        ("backend/app/main.py\nfrontend/frontend/src/App.tsx\n", "no"),
        ("", "no"),
    ],
)
def test_rebuilds_only_when_what_the_image_installs_changes(changed, expected):
    result = _deploy("--needs-rebuild", stdin=changed)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_the_filled_template_passes(tmp_path):
    result = _deploy("--check", env_file=_env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "env OK" in result.stdout


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"CORS_ORIGINS": "http://localhost:5173"}, "CORS_ORIGINS"),
        ({"JWT_SECRET_KEY": "change-me"}, "JWT_SECRET_KEY"),
        ({"POSTGRES_PASSWORD": ""}, "POSTGRES_PASSWORD"),
        ({"MINIO_SECRET_KEY": "short"}, "MINIO_SECRET_KEY"),
        ({"APP_ENV": "production"}, "APP_ENV"),
    ],
)
def test_a_bad_env_is_refused_before_anything_starts(tmp_path, changes, named):
    result = _deploy("--check", env_file=_env(tmp_path, **changes))
    assert result.returncode == 1
    assert named in result.stderr


def test_a_missing_env_is_refused(tmp_path):
    result = _deploy("--check", env_file=tmp_path / "absent.env")
    assert result.returncode == 1
    assert ".env.prod.example" in result.stderr
