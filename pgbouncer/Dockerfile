FROM alpine:3.23

# Pin the pooler version; no third-party container entrypoint or auth defaults.
RUN apk add --no-cache pgbouncer=1.25.1-r0 python3 postgresql18-client \
    && addgroup -S -g 10001 pooler \
    && adduser -S -D -H -u 10001 -G pooler pooler
COPY entrypoint.py healthcheck.py /opt/pgbouncer/
USER pooler
ENTRYPOINT ["python3", "/opt/pgbouncer/entrypoint.py"]
