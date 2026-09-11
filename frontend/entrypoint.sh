#!/bin/sh
set -eu

attempt=0
max_attempts=120

until wget -q -T 2 -O /dev/null http://backend:8000/api/health/; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "Backend did not become healthy within ${max_attempts} seconds." >&2
        exit 1
    fi
    sleep 1
done

exec /docker-entrypoint.sh "$@"
