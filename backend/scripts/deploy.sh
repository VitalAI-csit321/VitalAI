#!/usr/bin/env bash
#
# Bring the expo box to a release tag. Run on the box:
#   ~/vitalai/backend/scripts/deploy.sh expo-2026-10     # deploy that tag
#   ~/vitalai/backend/scripts/deploy.sh --check          # only validate .env
#
# The repo is bind-mounted into the api container, so a code change needs only
# a restart; the image is rebuilt only when what it installs changes. The
# frontend is built on the laptop and copied to frontend/frontend/dist (see
# the expo deployment plan); nothing here builds it.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.prod.yml"
ENV_FILE="${ENV_FILE:-.env}"
# What the image installs. A change to any of these needs a rebuild.
DEPS_RE='^backend/(Dockerfile|\.dockerignore|requirements\.(txt|lock))$'

preflight() {
    local key site cors jwt minio
    [ -f "$ENV_FILE" ] || { echo "no $ENV_FILE: copy .env.prod.example to .env and fill it" >&2; return 1; }
    for key in SITE_ADDRESS CORS_ORIGINS POSTGRES_PASSWORD JWT_SECRET_KEY MINIO_SECRET_KEY; do
        grep -qE "^${key}=.+" "$ENV_FILE" || { echo "$key is empty or missing in $ENV_FILE" >&2; return 1; }
    done
    site=$(sed -n 's/^SITE_ADDRESS=//p' "$ENV_FILE")
    cors=$(sed -n 's/^CORS_ORIGINS=//p' "$ENV_FILE" | cut -d, -f1)
    jwt=$(sed -n 's/^JWT_SECRET_KEY=//p' "$ENV_FILE")
    minio=$(sed -n 's/^MINIO_SECRET_KEY=//p' "$ENV_FILE")
    # Form and password-reset links in emails are built from the first CORS origin.
    [ "$cors" = "https://$site" ] || { echo "first CORS_ORIGINS entry is '$cors'; it must be https://$site" >&2; return 1; }
    [ "${#jwt}" -ge 32 ] || { echo "JWT_SECRET_KEY is shorter than 32 characters (use: openssl rand -hex 32)" >&2; return 1; }
    # MinIO refuses to start with a shorter root password.
    [ "${#minio}" -ge 8 ] || { echo "MINIO_SECRET_KEY is shorter than 8 characters (use: openssl rand -hex 32)" >&2; return 1; }
    if grep -qE '^APP_ENV=production$' "$ENV_FILE"; then
        echo "APP_ENV=production refuses to start on synthetic data; use staging" >&2
        return 1
    fi
}

# Changed file names on stdin. grep without -q reads all of stdin, so the
# writer never gets SIGPIPE, which pipefail would turn into a false "no".
needs_rebuild() {
    grep -E "$DEPS_RE" >/dev/null
}

case "${1:-}" in
    --check)
        preflight
        echo "env OK"
        exit 0
        ;;
    --needs-rebuild)
        if needs_rebuild; then echo yes; else echo no; fi
        exit 0
        ;;
    "" | -*)
        echo "usage: $0 <release-tag> | --check" >&2
        exit 2
        ;;
esac
TAG=$1

preflight
git fetch --tags --quiet origin
before=$(git rev-parse HEAD)
git checkout --quiet --detach "refs/tags/$TAG"
after=$(git rev-parse HEAD)

rebuilt=no
if ! docker image inspect vitalai-expo-api >/dev/null 2>&1 \
    || git diff --name-only "$before" "$after" | needs_rebuild; then
    echo "==> building the api image"
    $COMPOSE build api
    rebuilt=yes
fi

echo "==> migrations"
$COMPOSE run --rm api alembic upgrade head

echo "==> starting"
$COMPOSE up -d
if [ "$rebuilt" = no ] && [ "$before" != "$after" ]; then
    $COMPOSE restart api
fi

echo "==> health"
for _ in $(seq 1 45); do
    if $COMPOSE exec -T api python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=3)" 2>/dev/null; then
        echo "OK at $TAG ($after)"
        if [ "$rebuilt" = yes ]; then
            docker image prune -f >/dev/null
            docker builder prune -af >/dev/null
        fi
        exit 0
    fi
    sleep 2
done
echo "api did not become healthy; see: $COMPOSE logs --tail 100 api" >&2
exit 1
