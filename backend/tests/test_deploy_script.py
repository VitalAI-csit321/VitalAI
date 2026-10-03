"""scripts/deploy.sh: refuse a bad .env or a missing frontend build before
anything starts, and rebuild the image whenever what it installs changes."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy.sh"
TEMPLATE = SCRIPT.parents[1] / ".env.prod.example"
CONFIG = SCRIPT.parents[1] / "app" / "config.py"


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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Sarah Mitchell",
            "-c",
            "user.email=sarah.mitchell@harbourviewmedical.com.au",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    """A small git repo shaped like this one, with deploy.sh and config.py in place."""
    repo = tmp_path / "repo"
    backend = repo / "backend"
    (backend / "scripts").mkdir(parents=True)
    (backend / "app").mkdir()
    (backend / "scripts" / "deploy.sh").write_text(SCRIPT.read_text())
    (backend / "app" / "config.py").write_text(CONFIG.read_text())
    for name in ("Dockerfile", ".dockerignore", "requirements.txt", "requirements.lock"):
        (backend / name).write_text("v1\n")
    (backend / "app" / "main.py").write_text("v1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "First version")
    return repo


def _deps_rev(repo: Path) -> str:
    result = subprocess.run(
        ["bash", str(repo / "backend" / "scripts" / "deploy.sh"), "--deps-rev"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("changed", "rebuilds"),
    [
        ("Dockerfile", True),
        (".dockerignore", True),
        ("requirements.txt", True),
        ("requirements.lock", True),
        ("app/main.py", False),
    ],
)
def test_the_image_is_rebuilt_only_when_what_it_installs_changes(tmp_path, changed, rebuilds):
    """deploy.sh labels the image with this revision and rebuilds whenever the
    label differs, so a build that failed is retried by the next run."""
    repo = _repo(tmp_path)
    before = _deps_rev(repo)

    (repo / "backend" / changed).write_text("v2\n")
    _git(repo, "commit", "-qam", "Change one file")

    assert (_deps_rev(repo) != before) == rebuilds


def test_deploying_without_a_frontend_build_is_refused(tmp_path):
    repo = _repo(tmp_path)
    result = subprocess.run(
        ["bash", str(repo / "backend" / "scripts" / "deploy.sh"), "expo-2026-10"],
        capture_output=True,
        text=True,
        env=dict(os.environ, ENV_FILE=str(_env(tmp_path))),
    )
    assert result.returncode == 1
    assert "frontend/frontend/dist" in result.stderr


def test_a_misspelled_key_is_refused(tmp_path):
    env = _env(tmp_path)
    env.write_text(env.read_text() + "EMAIL_AUTO_SEND_ENABLE=false\n")
    result = _deploy("--check", env_file=env)
    assert result.returncode == 1
    assert "EMAIL_AUTO_SEND_ENABLE" in result.stderr


def test_every_setting_and_the_bedrock_api_key_are_accepted(tmp_path):
    from app.config import Settings

    env = _env(tmp_path)
    present = {line.split("=", 1)[0] for line in env.read_text().splitlines()}
    extra = [f"{name.upper()}=x" for name in Settings.model_fields if name.upper() not in present]
    env.write_text(env.read_text() + "\n".join([*extra, "AWS_BEARER_TOKEN_BEDROCK=x"]) + "\n")
    result = _deploy("--check", env_file=env)
    assert result.returncode == 0, result.stderr


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
