#!/usr/bin/env bash
# Run in a staging checkout. Build/check only; never enables AI or deploys services.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose config --quiet
docker compose build backend frontend
docker compose run --rm -e DB_DIRECT=true backend python manage.py check
docker compose run --rm -e DB_DIRECT=true backend python manage.py makemigrations --check --dry-run
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false \
  -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 \
  backend python manage.py test apps.ai_assistant --settings=config.ai_test_settings --noinput -v 2
printf '\nBuild and regression suite passed. No running application services were recreated.\n'
