import json
from datetime import UTC, datetime

from django.db import DatabaseError, connection, transaction
from redis.exceptions import RedisError
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .api_views import IsSystemAdministrator
from .db_metrics import PREFIX, WINDOWS, metrics_client, performance_history


class DatabaseMetricsThrottle(UserRateThrottle):
    rate = "30/minute"


def postgres_snapshot():
    if connection.vendor != "postgresql":
        return {"status": "unsupported", "engine": connection.vendor}
    client = metrics_client()
    key = f"{PREFIX}:postgres"
    try:
        stored = client.get(key) if client else None
        if stored:
            return json.loads(stored)
    except (RedisError, ValueError):
        pass
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '1500ms'")
            cursor.execute("""
                SELECT xact_commit, xact_rollback, blks_read, blks_hit,
                       tup_returned, tup_fetched, tup_inserted, tup_updated,
                       tup_deleted, temp_files, temp_bytes, deadlocks,
                       blk_read_time, blk_write_time, stats_reset,
                       current_setting('track_io_timing') = 'on',
                       (SELECT count(*) FROM pg_stat_activity
                        WHERE datname = current_database() AND state = 'active'
                          AND pid <> pg_backend_pid()),
                       (SELECT count(*) FROM pg_stat_activity
                        WHERE datname = current_database() AND wait_event_type = 'Lock'),
                       (SELECT count(*) FROM pg_stat_activity
                        WHERE datname = current_database())
                FROM pg_stat_database WHERE datname = current_database()
            """)
            row = cursor.fetchone()
        names = (
            "commits",
            "rollbacks",
            "blocks_read",
            "blocks_hit",
            "rows_returned",
            "rows_fetched",
            "rows_inserted",
            "rows_updated",
            "rows_deleted",
            "temp_files",
            "temp_bytes",
            "deadlocks",
            "block_read_ms",
            "block_write_ms",
            "stats_reset_at",
            "io_timing_enabled",
            "active_connections",
            "lock_waiters",
            "connections",
        )
        result = dict(zip(names, row))
        result["stats_reset_at"] = row[14].isoformat() if row[14] else None
        blocks = result["blocks_read"] + result["blocks_hit"]
        result["cache_hit_percent"] = (
            round(result["blocks_hit"] / blocks * 100, 2) if blocks else None
        )
        if not result["io_timing_enabled"]:
            result["block_read_ms"] = result["block_write_ms"] = None
        result.update(
            status="available",
            engine="postgresql",
            captured_at=datetime.now(UTC).isoformat(),
        )
        try:
            if client:
                client.set(key, json.dumps(result), ex=60)
        except RedisError:
            pass
        return result
    except DatabaseError:
        return {"status": "unavailable", "engine": "postgresql"}


class DatabasePerformanceView(APIView):
    permission_classes = [IsSystemAdministrator]
    throttle_classes = [DatabaseMetricsThrottle]

    def get(self, request):
        window = request.query_params.get("window", "1h")
        source = request.query_params.get("source", "all")
        if window not in WINDOWS or source not in {"all", "http", "worker"}:
            raise serializers.ValidationError("Choose a supported period and workload.")
        try:
            history = performance_history(window, source)
        except (RedisError, ValueError, OSError):
            history = {
                "status": "unavailable",
                "reason": "Telemetry storage is temporarily unavailable.",
            }
        response = Response(
            {
                **history,
                "generated_at": datetime.now(UTC).isoformat(),
                "postgres": postgres_snapshot(),
            }
        )
        response["Cache-Control"] = "no-store"
        return response
