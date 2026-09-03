FROM cloudflare/cloudflared:latest AS cloudflared

FROM alpine:3.22

RUN apk add --no-cache ca-certificates su-exec tini \
    && addgroup -S -g 65532 cloudflared \
    && adduser -S -D -H -u 65532 -G cloudflared cloudflared

COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY entrypoint.sh /usr/local/bin/cloudflared-entrypoint

RUN chmod 0755 /usr/local/bin/cloudflared /usr/local/bin/cloudflared-entrypoint

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/cloudflared-entrypoint"]
