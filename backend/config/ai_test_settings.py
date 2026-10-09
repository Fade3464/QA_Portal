"""Test-only settings; do not run an application server with this module.

Use --settings=config.ai_test_settings with manage.py test. PostgreSQL remains
Django's separate test database; cache, channels, Celery and email are isolated
in-memory, so tests don't mutate a running portal's Redis/cache or send mail.
"""
import os
import sys
from copy import deepcopy

if 'test' not in sys.argv and os.getenv('AI_TEST_RUNNER') != '1':
    raise RuntimeError('ai_test_settings is restricted to a test runner.')
from .settings import *  # noqa: F401,F403,E402

PRODUCTION = False
DEBUG = False
SECURE_SSL_REDIRECT = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1', 'backend']
CACHES = {'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION':'calllens-ai-isolated-tests'}}
CHANNEL_LAYERS = {'default': {'BACKEND':'channels.layers.InMemoryChannelLayer'}}
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
CELERY_TASK_ALWAYS_EAGER = False  # Queue in memory; never execute network tasks as a side effect.
CELERY_TASK_EAGER_PROPAGATES = True
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
DB_METRICS_ENABLED = False
DB_METRICS_REDIS_URL = ''
DATABASES = deepcopy(DATABASES)  # noqa: F405
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    test_name = os.getenv('AI_TEST_DB_NAME', 'test_calllens_ai')
    if not test_name.startswith('test_') or test_name == DATABASES['default']['NAME']:
        raise RuntimeError('Use a distinct test_-prefixed database name.')
    DATABASES['default']['TEST'] = {'NAME':test_name}
