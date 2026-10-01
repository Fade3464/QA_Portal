import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from redis.exceptions import ConnectionError
from rest_framework.test import APIClient

from apps.accounts.models import User

from . import db_metrics
from .db_metrics import DatabaseMetricsMiddleware, SQLCollector, query_kind, summarize
from .db_metrics_signals import begin_database_metrics, finish_database_metrics
from .db_metrics_views import postgres_snapshot
from .models import Branch, Company


@override_settings(
    DB_METRICS_ENABLED=True,
    DB_METRICS_REDIS_URL="redis://test/2",
    DB_METRICS_SLOW_MS=100,
)
class CollectorTests(SimpleTestCase):
    def setUp(self):
        db_metrics._retry_after = 0

    def tearDown(self):
        db_metrics._retry_after = 0

    def test_classification_does_not_guess_ambiguous_ctes(self):
        for sql, kind in [
            ("/* comment */ -- comment\n SELECT 1", "read"),
            ("INSERT INTO calls VALUES (1)", "write"),
            ("UPDATE calls SET a=1", "write"),
            ("DELETE FROM calls", "write"),
            ("WITH x AS (DELETE FROM calls RETURNING *) SELECT * FROM x", "other"),
            ("SAVEPOINT x", "other"),
            ("", "other"),
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(query_kind(sql)[0], kind)

    def test_execution_and_failure_are_preserved_without_sensitive_contents(self):
        collector = SQLCollector("http", "POST webhook")
        execute = Mock(return_value="result")
        with (
            patch.object(db_metrics.time, "perf_counter", side_effect=[1, 1.15]),
            patch.object(db_metrics.time, "time", return_value=120),
        ):
            self.assertEqual(
                collector(
                    execute, "SELECT secret FROM calls", ["private-value"], False, {}
                ),
                "result",
            )
        execute.assert_called_once_with(
            "SELECT secret FROM calls", ["private-value"], False, {}
        )
        failure = RuntimeError("private-database-error")
        with self.assertRaises(RuntimeError) as raised:
            collector(
                Mock(side_effect=failure),
                "UPDATE calls SET secret=%s",
                ["private-value"],
                False,
                {},
            )
        self.assertIs(raised.exception, failure)
        self.assertEqual(collector.buckets[120]["http:read:count"], 1)
        self.assertEqual(collector.buckets[120]["http:read:slow"], 1)
        self.assertEqual(
            sum(bucket["http:write:errors"] for bucket in collector.buckets.values()), 1
        )
        encoded = json.dumps(collector.slow)
        for secret in (
            "private-value",
            "private-database-error",
            "SELECT secret",
            "UPDATE calls",
        ):
            self.assertNotIn(secret, encoded)

    def test_slow_samples_are_bounded(self):
        collector = SQLCollector("worker", "calls.fetch_recording")
        for _ in range(12):
            with self.assertRaises(ValueError):
                collector(Mock(side_effect=ValueError), "SELECT 1", None, False, {})
        self.assertEqual(len(collector.slow), 5)

    def test_flush_uses_atomic_aggregates_and_bounded_retention(self):
        client = Mock()
        pipeline = client.pipeline.return_value
        collector = SQLCollector("worker", "calls.fetch_recording")
        collector.buckets = {
            120: {"worker:read:count": 1, "worker:read:max": 12},
            180: {"worker:read:count": 2, "worker:read:max": 8},
        }
        collector.slow = [{"operation": "SELECT"}]
        with patch.object(db_metrics, "metrics_client", return_value=client):
            collector.flush()
        self.assertEqual(pipeline.eval.call_count, 3)
        hour_call = pipeline.eval.call_args_list[-1].args
        self.assertEqual(hour_call[2], f"{db_metrics.PREFIX}:hour:0")
        hour_values = dict(zip(hour_call[4::2], hour_call[5::2]))
        self.assertEqual(hour_values["worker:read:count"], "3")
        self.assertEqual(hour_values["worker:read:max"], "12")
        self.assertEqual(hour_call[3], str(90 * 86400))
        pipeline.ltrim.assert_called_once_with(f"{db_metrics.PREFIX}:slow", 0, 199)
        pipeline.execute.assert_called_once()

    def test_storage_failure_opens_circuit_without_failing_work(self):
        client = Mock()
        client.pipeline.return_value.execute.side_effect = ConnectionError("secret")
        collector = SQLCollector("http", "named-route")
        collector.buckets = {120: {"http:read:count": 1}}
        with (
            patch.object(db_metrics, "metrics_client", return_value=client),
            self.assertLogs(db_metrics.logger, level="WARNING") as logs,
        ):
            collector.flush()
            collector.flush()
        client.pipeline.return_value.execute.assert_called_once()
        self.assertNotIn("secret", str(logs.output))

    def test_summary_is_weighted_source_filtered_and_histogram_based(self):
        rows = [
            {
                "http:read:count": "10",
                "http:read:ms": "100",
                "http:read:max": "10",
                "http:read:h2": "10",
            },
            {
                "http:read:count": "30",
                "http:read:ms": "600",
                "http:read:max": "20",
                "http:read:h3": "30",
                "worker:read:count": "1",
                "worker:read:ms": "9000",
                "worker:read:max": "9000",
                "worker:read:h10": "1",
            },
        ]
        result = summarize(rows, "http", 120)["read"]
        self.assertEqual(result["average_ms"], 17.5)
        self.assertEqual(result["count"], 40)
        self.assertEqual(result["max_ms"], 20)
        self.assertEqual(result["p95_upper_ms"], 25)
        self.assertAlmostEqual(result["queries_per_second"], 0.333)
        self.assertTrue(summarize(rows, "worker")["read"]["p95_overflow"])
        self.assertIsNone(summarize([], "all")["write"]["average_ms"])

    def test_history_excludes_incomplete_interval_and_requires_comparison_samples(self):
        pipeline = Mock()
        # 60 prior minutes followed by 60 current minutes.
        old = {"http:read:count": "20", "http:read:ms": "400", "http:read:h3": "20"}
        new = {"http:read:count": "20", "http:read:ms": "200", "http:read:h2": "20"}
        worker = {"worker:write:count": "1"}
        pipeline.execute.return_value = (
            [old] + [{}] * 59 + [new, worker] + [{}] * 58 + [[], ["3600", "7199", None]]
        )
        client = Mock()
        client.pipeline.return_value = pipeline
        with (
            patch.object(db_metrics, "metrics_client", return_value=client),
            patch.object(db_metrics.time, "time", return_value=7230),
        ):
            result = db_metrics.performance_history("1h", "http")
        self.assertEqual(result["latency_change_percent"]["read"], -50)
        self.assertIsNone(result["latency_change_percent"]["write"])
        self.assertEqual(result["observed_buckets"], 1)
        self.assertEqual(result["summary"]["write"]["count"], 0)
        self.assertEqual(pipeline.hgetall.call_count, 120)
        self.assertTrue(pipeline.hgetall.call_args.args[0].endswith(":7140"))

    def test_middleware_skips_itself_and_uses_route_not_url(self):
        factory = RequestFactory()
        with patch.object(db_metrics, "SQLCollector") as cls:
            middleware = DatabaseMetricsMiddleware(lambda request: HttpResponse("ok"))
            middleware(factory.get("/api/v1/administration/database-performance/"))
            cls.assert_not_called()
            request = factory.get("/api/private-token/", {"token": "secret"})
            request.resolver_match = SimpleNamespace(view_name="safe-view", route="")
            middleware(request)
            self.assertEqual(
                cls.return_value.__enter__.return_value.workload, "GET safe-view"
            )


@override_settings(
    DB_METRICS_ENABLED=True,
    DB_METRICS_REDIS_URL="redis://test/2",
    DB_METRICS_SLOW_MS=100,
)
class DatabaseWrapperTests(TestCase):
    def test_postgres_snapshot_calculates_cache_hits_and_hides_disabled_io_timing(self):
        fake_connection = MagicMock(vendor="postgresql")
        cursor = fake_connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            10,
            2,
            25,
            75,
            100,
            90,
            5,
            4,
            3,
            0,
            0,
            1,
            100.0,
            200.0,
            None,
            False,
            2,
            1,
            4,
        )
        with (
            patch("apps.tenancy.db_metrics_views.connection", fake_connection),
            patch("apps.tenancy.db_metrics_views.metrics_client", return_value=None),
        ):
            result = postgres_snapshot()
        self.assertEqual(result["cache_hit_percent"], 75)
        self.assertEqual(result["lock_waiters"], 1)
        self.assertEqual(result["status"], "available")
        self.assertIsNone(result["block_read_ms"])
        self.assertIsNone(result["block_write_ms"])
        self.assertEqual(
            cursor.execute.call_args_list[0].args[0],
            "SET LOCAL statement_timeout = '1500ms'",
        )

    def test_postgres_snapshot_uses_shared_cache_without_touching_database(self):
        fake_connection = Mock(vendor="postgresql")
        client = Mock()
        client.get.return_value = json.dumps(
            {"status": "available", "engine": "postgresql"}
        )
        with (
            patch("apps.tenancy.db_metrics_views.connection", fake_connection),
            patch("apps.tenancy.db_metrics_views.metrics_client", return_value=client),
        ):
            self.assertEqual(postgres_snapshot()["status"], "available")
        fake_connection.cursor.assert_not_called()

    def test_real_connection_wrapper_installs_and_cleans_up(self):
        with patch.object(SQLCollector, "flush"):
            with SQLCollector("http", "test") as collector:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    self.assertEqual(cursor.fetchone(), (1,))
            self.assertNotIn(collector, connection.execute_wrappers)
        self.assertEqual(
            sum(row["http:read:count"] for row in collector.buckets.values()), 1
        )

    def test_worker_signals_capture_task_sql_and_remove_wrapper_after_failure(self):
        task = SimpleNamespace(name="calls.fetch_recording", request=SimpleNamespace())
        with patch.object(SQLCollector, "flush") as flush:
            begin_database_metrics(task=task)
            collector = task.request._database_metrics
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            finish_database_metrics(task=task, state="FAILURE")
            finish_database_metrics(task=task)
        self.assertFalse(hasattr(task.request, "_database_metrics"))
        self.assertNotIn(collector, connection.execute_wrappers)
        flush.assert_called_once()
        self.assertEqual(
            sum(row["worker:read:count"] for row in collector.buckets.values()), 1
        )


@override_settings(
    DB_METRICS_REDIS_URL="",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class DatabasePerformanceApiTests(TestCase):
    def setUp(self):
        self.api = APIClient()
        self.url = reverse("administration-database-performance")
        self.admin = User.objects.create_superuser(
            email="db-admin@example.com",
            password="strong-secret",
            first_name="Database",
            last_name="Administrator",
            role=User.Role.ADMINISTRATOR,
        )

    def test_admin_gets_no_store_and_explicit_disabled_history(self):
        self.api.force_authenticate(self.admin)
        response = self.api.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.data["status"], "disabled")

    def test_anonymous_and_every_non_superuser_role_are_denied(self):
        self.assertEqual(self.api.get(self.url).status_code, 403)
        company = Company.objects.create(name="Metrics", slug="metrics")
        branch = Branch.objects.create(company=company, name="Metrics", code="metrics")
        for role in User.Role.values:
            if role == User.Role.ADMINISTRATOR:
                continue  # The model already forbids this role without superuser status.
            with self.subTest(role=role):
                user = User.objects.create_user(
                    email=f"metrics-{role}@example.com",
                    password="strong-secret",
                    first_name="Metrics",
                    last_name="User",
                    role=role,
                    company=company,
                    branch=branch,
                )
                self.api.force_authenticate(user)
                self.assertEqual(self.api.get(self.url).status_code, 403)
        self.admin.is_active = False
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.get(self.url).status_code, 403)

    def test_rejects_invalid_filter_values(self):
        self.api.force_authenticate(self.admin)
        for query in ("?window=forever", "?source=private", "?window=0"):
            self.assertEqual(self.api.get(self.url + query).status_code, 400)

    def test_outage_returns_safe_status_and_no_credentials(self):
        self.api.force_authenticate(self.admin)
        with patch(
            "apps.tenancy.db_metrics_views.performance_history",
            side_effect=ConnectionError("redis://secret@private"),
        ):
            response = self.api.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "unavailable")
        self.assertNotIn("secret", response.content.decode())
