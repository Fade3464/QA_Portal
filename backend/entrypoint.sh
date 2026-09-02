#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py bootstrap_admin
# Nginx owns the sanitized access log. Uvicorn access logging is disabled so
# VICIdial query-string credentials can never be written to application logs.
exec uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*" --no-access-log
