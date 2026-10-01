"""Regression coverage for pool routing, maintenance, and secret handling."""

import importlib.util
import tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_settings

ROOT = Path(__file__).resolve().parents[2]
pooler_path = ROOT.parent / "pgbouncer" / "entrypoint.py"
if pooler_path.exists():
    spec = importlib.util.spec_from_file_location("pooler_entrypoint", pooler_path)
    pooler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pooler)
else:
    pooler = None  # The backend-only Docker image does not include pooler sources.


class DatabaseRoutingTests(SimpleTestCase):
    def setUp(self):
        self.env = {
            "PGHOST": "db",
            "PGPORT": "5432",
            "PGDATABASE": "calllens",
            "PGUSER": "app",
            "PGPASSWORD": "a:/@?#%$'\"strong-secret",
            "DB_USE_PGBOUNCER": "true",
            "PGBOUNCER_HOST": "pgbouncer",
        }

    def test_web_and_worker_use_transaction_pool_safely(self):
        result = database_settings(self.env, production=True)
        self.assertEqual((result["HOST"], result["PORT"]), ("pgbouncer", 6432))
        self.assertEqual(result["PASSWORD"], self.env["PGPASSWORD"])
        self.assertEqual(result["CONN_MAX_AGE"], 0)
        self.assertTrue(result["DISABLE_SERVER_SIDE_CURSORS"])
        self.assertIsNone(result["OPTIONS"]["prepare_threshold"])
        self.assertEqual(result["OPTIONS"]["connect_timeout"], 5)

    def test_direct_maintenance_and_rollback_bypass_pool(self):
        for switch in ({"DB_DIRECT": "true"}, {"DB_USE_PGBOUNCER": "false"}):
            with self.subTest(switch=switch):
                result = database_settings({**self.env, **switch}, production=True)
                self.assertEqual((result["HOST"], result["PORT"]), ("db", 5432))
                self.assertNotIn("prepare_threshold", result["OPTIONS"])
                self.assertFalse(result["DISABLE_SERVER_SIDE_CURSORS"])

    def test_separate_credentials_take_precedence_over_stale_url(self):
        result = database_settings(
            {**self.env, "DATABASE_URL": "postgresql://stale:secret@old:bad/old"}
        )
        self.assertEqual(result["NAME"], "calllens")
        self.assertEqual(result["USER"], "app")

    def test_native_url_is_supported_and_percent_decoded(self):
        result = database_settings(
            {"DATABASE_URL": "postgresql://app:p%40ss%2Fword@localhost:5433/calllens"}
        )
        self.assertEqual(result["PASSWORD"], "p@ss/word")
        self.assertEqual((result["HOST"], result["PORT"]), ("localhost", 5433))

    def test_development_sqlite_and_production_validation_remain(self):
        self.assertIsNone(database_settings({}))
        for env in (
            {},
            {**self.env, "PGPASSWORD": ""},
            {**self.env, "PGPASSWORD": "qa_portal_dev_only"},
            {**self.env, "PGBOUNCER_PORT": "0"},
            {"DATABASE_URL": "mysql://app:secret@host/db"},
        ):
            with (
                self.subTest(env_keys=list(env)),
                self.assertRaises(ImproperlyConfigured),
            ):
                database_settings(env, production=True)


@skipUnless(
    pooler is not None,
    "Pooler image contract tests require the full repository checkout",
)
class PoolerConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.env = {
            "POSTGRES_DB": "calllens",
            "POSTGRES_USER": "app",
            "POSTGRES_PASSWORD": 'safe\\password"with@symbols/#;$',
        }

    def test_transaction_pool_is_bounded_and_console_read_only(self):
        config, users = pooler.configuration(self.env)
        for setting in (
            "pool_mode = transaction",
            "auth_type = scram-sha-256",
            "default_pool_size = 20",
            "reserve_pool_size = 5",
            "max_db_connections = 25",
            "max_client_conn = 200",
            "query_wait_timeout = 30",
            "stats_users = app",
            "max_prepared_statements = 0",
        ):
            self.assertIn(setting, config)
        self.assertNotIn("admin_users", config)
        self.assertNotIn(self.env["POSTGRES_PASSWORD"], config)
        self.assertEqual(users, '"app" "safe\\password""with@symbols/#;$"\n')

    def test_rejects_injection_and_invalid_pool_limits_without_leaking_values(self):
        for override in (
            {"POSTGRES_PASSWORD": "private\nsecret"},
            {"POSTGRES_USER": "app\nadmin_users=app"},
            {"POSTGRES_DB": "pgbouncer"},
            {"PGHOST": "db port=0"},
            {"PGBOUNCER_POOL_SIZE": "0"},
            {"PGBOUNCER_MAX_CLIENT_CONN": "5"},
            {"PGBOUNCER_QUERY_WAIT_TIMEOUT": "-1"},
        ):
            with (
                self.subTest(fields=list(override)),
                self.assertRaises(ValueError) as error,
            ):
                pooler.configuration({**self.env, **override})
            self.assertNotIn("private", str(error.exception))

    def test_generated_secrets_only_exist_in_private_runtime_files(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pooler, "RUNTIME", Path(directory) / "runtime"),
        ):
            # write_configuration sets a restrictive process umask; restore it
            # after this test to avoid affecting unrelated test-created files.
            import os

            previous = os.umask(0o077)
            try:
                path = pooler.write_configuration(self.env)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(
                    (path.parent / "users.txt").stat().st_mode & 0o777, 0o600
                )
            finally:
                os.umask(previous)

    def test_compose_and_startup_preserve_direct_maintenance_and_queue_topology(self):
        compose = (ROOT.parent / "compose.yml").read_text()
        entrypoint = (ROOT / "entrypoint.sh").read_text()
        self.assertIn("DB_DIRECT=true python manage.py migrate", entrypoint)
        self.assertIn("DB_DIRECT=true python manage.py bootstrap_admin", entrypoint)
        self.assertIn(
            '"--queues=recordings,celery", "--concurrency=6", "--prefetch-multiplier=1"',
            compose,
        )
        # The pooler is internal-only: no published ports or durable secret files.
        block = compose.split("  pgbouncer:\n", 1)[1].split("  redis:\n", 1)[0]
        self.assertNotIn("    ports:", block)
        self.assertNotIn("    volumes:", block)
        self.assertIn("cap_drop: [ALL]", block)
