from __future__ import annotations

import os
import base64
import hashlib
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


PRODUCTION = env_bool("PRODUCTION", False)
# Production is an authoritative security boundary. A stale development value
# in a copied .env file must never turn debug mode back on.
DEBUG = False if PRODUCTION else env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "development-only-change-before-deployment"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is false")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"
    if DEBUG
    else "",
)
if not PRODUCTION:
    # Quick Tunnels receive a random hostname on each container start. Limit the
    # development exception to Cloudflare's dedicated temporary-tunnel domain.
    ALLOWED_HOSTS.append(".trycloudflare.com")
    CSRF_TRUSTED_ORIGINS.append("https://*.trycloudflare.com")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "axes",
    "apps.tenancy",
    "apps.accounts",
    "apps.calls",
    "apps.dashboard",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

if os.getenv("DATABASE_URL"):
    from urllib.parse import urlparse

    database_url = urlparse(os.environ["DATABASE_URL"])
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": database_url.path.lstrip("/"),
            "USER": database_url.username,
            "PASSWORD": database_url.password,
            "HOST": database_url.hostname,
            "PORT": database_url.port or 5432,
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

LANGUAGE_CODE = "en-us"
# Persist datetimes as UTC (USE_TZ=True), but interpret and present calendar
# values in New York. The IANA zone handles EST/EDT transitions automatically.
TIME_ZONE = os.getenv("TIME_ZONE", "America/New_York")
if TIME_ZONE != "America/New_York":
    raise ImproperlyConfigured(
        "TIME_ZONE must be America/New_York so backend and frontend calendar "
        "boundaries cannot diverge."
    )
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "apps.accounts.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_RATES": {"login": "10/minute", "password_reset": "5/hour"},
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache"
        if os.getenv("REDIS_URL")
        else "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": os.getenv("CACHE_URL", "redis://localhost:6379/2")
        if os.getenv("REDIS_URL")
        else "qa-portal-cache",
    }
}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer"
        if os.getenv("REDIS_URL")
        else "channels.layers.InMemoryChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]} if os.getenv("REDIS_URL") else {},
    }
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 500
CELERY_TASK_SOFT_TIME_LIMIT = 270
CELERY_TASK_TIME_LIMIT = 300
# Tasks use explicit public names (``calls.resolve_recording`` and
# ``calls.fetch_recording``), so routing must match those names rather than the
# Python module path.
CELERY_TASK_ROUTES = {
    "calls.*": {"queue": "recordings"},
    "notifications.*": {"queue": "celery"},
}

AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_HTTP_RESPONSE_CODE = 429

SESSION_COOKIE_NAME = "qa_portal_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_SAVE_EVERY_REQUEST = True
PASSWORD_RESET_TIMEOUT = 60 * 60
CSRF_COOKIE_NAME = "qa_portal_csrf"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Likewise, production traffic must remain HTTPS-only even if a development
# .env still contains SECURE_SSL_REDIRECT=false.
SECURE_SSL_REDIRECT = True if PRODUCTION else env_bool("SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = int(
    os.getenv("SECURE_HSTS_SECONDS", "31536000" if not DEBUG else "0")
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "QA Portal <noreply@example.com>")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
QA_REPORT_EMAIL_ENABLED = env_bool("QA_REPORT_EMAIL_ENABLED", False)
QA_RETURN_EMAIL_ENABLED = env_bool("QA_RETURN_EMAIL_ENABLED", False)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
DIALER_CREDENTIAL_KEY = os.getenv("DIALER_CREDENTIAL_KEY", "")
if not DIALER_CREDENTIAL_KEY:
    if DEBUG:
        DIALER_CREDENTIAL_KEY = base64.urlsafe_b64encode(
            hashlib.sha256(SECRET_KEY.encode()).digest()
        ).decode()
    else:
        raise ImproperlyConfigured(
            "DIALER_CREDENTIAL_KEY is required when DEBUG is false"
        )
RECORDING_RETRY_DELAYS = [
    int(value) for value in env_list("RECORDING_RETRY_DELAYS", "5,15,30,60,120")
]
RECORDING_MAX_BYTES = int(os.getenv("RECORDING_MAX_BYTES", str(250 * 1024 * 1024)))
RECORDING_DOWNLOAD_VERIFY_TLS = env_bool("RECORDING_DOWNLOAD_VERIFY_TLS", True)
RECORDINGS_ROOT = Path(os.getenv("RECORDINGS_ROOT", MEDIA_ROOT / "recordings"))
SECURE_REDIRECT_EXEMPT = [
    r"^api/health/$",
]
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"}
    },
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    # httpx logs complete query strings at INFO. VICIdial's legacy API carries
    # credentials in its query string, so only warnings/errors may propagate.
    "loggers": {
        "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "httpcore": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
