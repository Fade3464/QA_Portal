"""PostgreSQL routing: runtime pooling, explicit direct maintenance access."""

from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def enabled(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def database_settings(env, *, production=False):
    url = env.get("DATABASE_URL", "")
    # Compose passes separate libpq fields, so reserved characters in secrets
    # never have to be interpolated into a URL.
    if not env.get("PGHOST") and not url:
        if production:
            raise ImproperlyConfigured(
                "PostgreSQL configuration is required in production"
            )
        return None
    parsed = urlparse("" if env.get("PGHOST") else url)
    if (
        url
        and not env.get("PGHOST")
        and parsed.scheme not in {"postgres", "postgresql"}
    ):
        raise ImproperlyConfigured("DATABASE_URL must use PostgreSQL")
    password = env.get("PGPASSWORD", unquote(parsed.password or ""))
    if production and (not password or password == "qa_portal_dev_only"):
        raise ImproperlyConfigured(
            "PostgreSQL must use a non-default database password in production"
        )
    pooled = enabled(env.get("DB_USE_PGBOUNCER", False)) and not enabled(
        env.get("DB_DIRECT", False)
    )
    direct_host = env.get("PGHOST") or parsed.hostname
    host = env.get("PGBOUNCER_HOST", "pgbouncer") if pooled else direct_host
    try:
        port = (
            env.get("PGBOUNCER_PORT", "6432")
            if pooled
            else env.get("PGPORT") or parsed.port or 5432
        )
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        raise ImproperlyConfigured(
            "PostgreSQL port must be between 1 and 65535"
        ) from None
    name = env.get("PGDATABASE", unquote(parsed.path.lstrip("/")))
    user = env.get("PGUSER", unquote(parsed.username or ""))
    if not direct_host or not host or not name or not user:
        raise ImproperlyConfigured("PostgreSQL host, database and user are required")
    options = {
        "connect_timeout": 5,
        "application_name": env.get("PGAPPNAME", "calllens"),
    }
    if pooled:
        # No session-local prepared statements may survive transaction handoff.
        options["prepare_threshold"] = None
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": name,
        "USER": user,
        "PASSWORD": password,
        "HOST": host,
        "PORT": port,
        "CONN_MAX_AGE": 0,  # Django's ASGI connection lifecycle recommendation.
        "CONN_HEALTH_CHECKS": True,
        "DISABLE_SERVER_SIDE_CURSORS": pooled,
        "OPTIONS": options,
    }
