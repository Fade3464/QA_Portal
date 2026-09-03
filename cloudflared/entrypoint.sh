#!/bin/sh
set -eu

production=$(printf '%s' "${PRODUCTION:-false}" | tr '[:upper:]' '[:lower:]')
origin_url=${CLOUDFLARED_ORIGIN_URL:-http://frontend:80}
url_file=${CLOUDFLARED_URL_FILE:-/runtime/cloudflared-url.txt}
url_directory=$(dirname "$url_file")

mkdir -p "$url_directory"
rm -f "$url_file" "$url_file.tmp"
: > "$url_file"

case "$production" in
  true|1|yes|on)
    echo "PRODUCTION=true; Cloudflare Quick Tunnel is disabled."
    exit 0
    ;;
  false|0|no|off)
    ;;
  *)
    echo "Invalid PRODUCTION value: ${PRODUCTION}. Use true or false." >&2
    exit 64
    ;;
esac

output_pipe=/tmp/cloudflared-output
cloudflared_pid=''

rm -f "$output_pipe"
mkfifo "$output_pipe"

stop_cloudflared() {
  if [ -n "$cloudflared_pid" ] && kill -0 "$cloudflared_pid" 2>/dev/null; then
    kill -TERM "$cloudflared_pid" 2>/dev/null || true
    wait "$cloudflared_pid" 2>/dev/null || true
  fi
}

trap stop_cloudflared HUP INT TERM EXIT

su-exec cloudflared:cloudflared \
  /usr/local/bin/cloudflared --no-autoupdate tunnel --url "$origin_url" \
  >"$output_pipe" 2>&1 &
cloudflared_pid=$!

while IFS= read -r line; do
  printf '%s\n' "$line"
  tunnel_url=$(printf '%s\n' "$line" | sed -n 's#.*\(https://[-[:alnum:].]*\.trycloudflare\.com\).*#\1#p')
  if [ -n "$tunnel_url" ]; then
    printf '%s\n' "$tunnel_url" > "$url_file.tmp"
    mv "$url_file.tmp" "$url_file"
    echo "Cloudflare Quick Tunnel URL saved to $url_file"
  fi
done < "$output_pipe"

set +e
wait "$cloudflared_pid"
status=$?
set -e
cloudflared_pid=''
trap - HUP INT TERM EXIT
rm -f "$output_pipe"
exit "$status"
