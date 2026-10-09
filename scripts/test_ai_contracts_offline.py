#!/usr/bin/env python3
"""Run pure contract tests when Django is unavailable. Not an ORM/integration test."""
import importlib.util
import pathlib
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'backend'))
if importlib.util.find_spec('django') is None:
    django = types.ModuleType('django')
    utils = types.ModuleType('django.utils')
    tz = types.SimpleNamespace(localdate=lambda: datetime.now(ZoneInfo('America/New_York')).date(),
                               get_current_timezone=lambda: ZoneInfo('America/New_York'))
    utils.timezone = tz
    sys.modules.update({'django':django, 'django.utils':utils})
    print('OFFLINE: pure contracts only; calendar clock shim, no ORM/database/provider execution.', flush=True)
else:
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from apps.ai_assistant import tests_contracts
suite = unittest.defaultTestLoader.loadTestsFromModule(tests_contracts)
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
