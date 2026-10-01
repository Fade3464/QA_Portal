#!/bin/sh
set -eu

# Schema/data migrations may depend on session-scoped database features.
# Scope direct routing to these processes, never the ASGI application.
DB_DIRECT=true python manage.py migrate --noinput
DB_DIRECT=true python manage.py bootstrap_admin
# Nginx owns the sanitized access log. Uvicorn access logging is disabled so
# VICIdial query-string credentials can never be written to application logs.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*" --no-access-log
