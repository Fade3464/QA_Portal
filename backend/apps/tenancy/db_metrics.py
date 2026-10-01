"""Bounded SQL execution telemetry; never store SQL, parameters or user IDs."""

import json
import logging
import math
import os
import re
import time
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import lru_cache

from django.conf import settings
from django.db import connections
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

logger = logging.getLogger(__name__)
PREFIX = "calllens:db-metrics:v1"
KINDS = ("read", "write", "other")
BOUNDS_MS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000)
WINDOWS = {"1h": (60, 60), "24h": (60, 1440), "7d": (3600, 168), "30d": (3600, 720)}
_retry_after = 0.0

# Atomically increment counters and update maxima across concurrent workers.
UPDATE = """
for i = 2, #ARGV, 2 do
  local field, value = ARGV[i], tonumber(ARGV[i+1])
  if string.sub(field, -4) == ':max' then
    local old = tonumber(redis.call('HGET', KEYS[1], field) or '0')
    if value > old then redis.call('HSET', KEYS[1], field, value) end
  else
    redis.call('HINCRBYFLOAT', KEYS[1], field, value)
  end
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
"""


@lru_cache(maxsize=4)
def _client(url, pid):
    # A pool per process, never a socket inherited by Celery children.
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=0.15,
        socket_timeout=0.2,
        retry_on_timeout=False,
        retry=Retry(NoBackoff(), 0),
        max_connections=16,
    )


def metrics_client():
    if not settings.DB_METRICS_ENABLED or not settings.DB_METRICS_REDIS_URL:
        return None
    return _client(settings.DB_METRICS_REDIS_URL, os.getpid())


def query_kind(sql):
    # Strip only leading SQL comments. Ambiguous statements (including WITH)
    # are intentionally kept in Other, rather than misreported as reads.
    text = re.sub(r"\A(?:\s|/\*.*?\*/|--[^\n]*(?:\n|$))*", "", str(sql), flags=re.S)
    verb = text.split(None, 1)[0].upper() if text else ""
    if verb in {"SELECT", "SHOW", "VALUES"}:
        return "read", verb
    if verb in {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"}:
        return "write", verb
    return "other", verb if verb in {
        "WITH",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "RELEASE",
        "CREATE",
        "ALTER",
        "DROP",
        "PRAGMA",
    } else "OTHER"


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


class SQLCollector:
    def __init__(self, source, workload):
        self.source = source
        self.workload = workload
        self.buckets = {}
        self.slow = []
        self.stack = ExitStack()

    def __enter__(self):
        for connection in connections.all():
            self.stack.enter_context(connection.execute_wrapper(self))
        return self

    def __exit__(self, *exc):
        self.stack.close()
        self.flush()

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        failed = False
        try:
            return execute(sql, params, many, context)
        except Exception:
            failed = True
            raise
        finally:
            elapsed = max(0, (time.perf_counter() - started) * 1000)
            stamp = time.time()
            kind, verb = query_kind(sql)
            bucket = self.buckets.setdefault(int(stamp // 60) * 60, Counter())
            base = f"{self.source}:{kind}"
            bucket[f"{base}:count"] += 1
            bucket[f"{base}:ms"] += elapsed
            bucket[f"{base}:max"] = max(bucket[f"{base}:max"], elapsed)
            bucket[f"{base}:errors"] += int(failed)
            bucket[f"{base}:slow"] += int(elapsed >= settings.DB_METRICS_SLOW_MS)
            band = next(
                (i for i, limit in enumerate(BOUNDS_MS) if elapsed <= limit),
                len(BOUNDS_MS),
            )
            bucket[f"{base}:h{band}"] += 1
            if failed or elapsed >= settings.DB_METRICS_SLOW_MS:
                self.slow.append(
                    {
                        "at": iso(stamp),
                        "timestamp": stamp,
                        "source": self.source,
                        "kind": kind,
                        "operation": verb,
                        "duration_ms": round(elapsed, 3),
                        "failed": failed,
                    }
                )
                # Keep only the slowest five per request/task, including failures.
                self.slow.sort(
                    key=lambda item: (item["failed"], item["duration_ms"]), reverse=True
                )
                del self.slow[5:]

    def flush(self):
        global _retry_after
        if not self.buckets or time.monotonic() < _retry_after:
            return
        try:
            client = metrics_client()
            if client is None:
                return
            pipeline = client.pipeline(transaction=False)
            hourly = {}
            for stamp, values in self.buckets.items():
                args = [str(48 * 3600)]
                for key, value in values.items():
                    args.extend([key, str(value)])
                pipeline.eval(UPDATE, 1, f"{PREFIX}:minute:{stamp}", *args)
                hour = stamp // 3600 * 3600
                summary = hourly.setdefault(hour, Counter())
                for key, value in values.items():
                    summary[key] = (
                        max(summary[key], value)
                        if key.endswith(":max")
                        else summary[key] + value
                    )
            for stamp, values in hourly.items():
                args = [str(90 * 86400)]
                for key, value in values.items():
                    args.extend([key, str(value)])
                pipeline.eval(UPDATE, 1, f"{PREFIX}:hour:{stamp}", *args)
            if self.slow:
                pipeline.lpush(
                    f"{PREFIX}:slow",
                    *[
                        json.dumps({**item, "workload": self.workload[:180]})
                        for item in self.slow
                    ],
                )
                pipeline.ltrim(f"{PREFIX}:slow", 0, 199)
                pipeline.expire(f"{PREFIX}:slow", 90 * 86400)
            pipeline.set(
                f"{PREFIX}:last:{self.source}", str(time.time()), ex=90 * 86400
            )
            pipeline.set(f"{PREFIX}:first", str(time.time()), nx=True, ex=90 * 86400)
            pipeline.execute()
        except (RedisError, ValueError, OSError):
            # Observability must never fail a call, task, or authentication flow.
            _retry_after = time.monotonic() + 60
            logger.warning(
                "Database telemetry storage unavailable; retrying in 60 seconds"
            )


class DatabaseMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            not settings.DB_METRICS_ENABLED
            or not settings.DB_METRICS_REDIS_URL
            or request.path == "/api/health/"
            or request.path.startswith("/api/v1/administration/database-performance/")
        ):
            return self.get_response(request)
        with SQLCollector("http", "unmatched") as collector:
            try:
                return self.get_response(request)
            finally:
                match = getattr(request, "resolver_match", None)
                # Names/routes, never a URL containing IDs, tokens or query parameters.
                collector.workload = (
                    f"{request.method} {match.view_name or match.route}"
                    if match
                    else "unmatched"
                )


def summarize(rows, source="all", seconds=60):
    result = {}
    sources = ("http", "worker") if source == "all" else (source,)
    for kind in KINDS:
        total = Counter()
        peak = 0
        for row in rows:
            for origin in sources:
                base = f"{origin}:{kind}:"
                for key, value in row.items():
                    if key.startswith(base):
                        metric = key[len(base) :]
                        if metric == "max":
                            peak = max(peak, float(value))
                        else:
                            total[metric] += float(value)
        count = int(total["count"])
        p95 = None
        overflow = False
        if count:
            cumulative = 0
            for i in range(len(BOUNDS_MS) + 1):
                cumulative += total[f"h{i}"]
                if cumulative >= math.ceil(count * 0.95):
                    overflow = i == len(BOUNDS_MS)
                    p95 = BOUNDS_MS[-1] if overflow else BOUNDS_MS[i]
                    break
        result[kind] = {
            "count": count,
            "average_ms": round(total["ms"] / count, 3) if count else None,
            "p95_upper_ms": p95,
            "p95_overflow": overflow,
            "max_ms": round(peak, 3) if count else None,
            "queries_per_second": round(count / seconds, 3),
            "errors": int(total["errors"]),
            "slow": int(total["slow"]),
        }
    return result


def performance_history(window, source):
    client = metrics_client()
    if client is None:
        return {
            "status": "disabled",
            "reason": "Set DB_METRICS_REDIS_URL or CACHE_URL to enable shared history.",
        }
    step, length = WINDOWS[window]
    end = int(time.time() // step) * step
    start = end - length * step
    resolution = "minute" if step == 60 else "hour"
    stamps = list(range(start - length * step, end, step))
    pipeline = client.pipeline(transaction=False)
    for stamp in stamps:
        pipeline.hgetall(f"{PREFIX}:{resolution}:{stamp}")
    pipeline.lrange(f"{PREFIX}:slow", 0, 199)
    pipeline.mget([f"{PREFIX}:first", f"{PREFIX}:last:http", f"{PREFIX}:last:worker"])
    values = pipeline.execute()
    rows = values[: len(stamps)]
    current = summarize(rows[length:], source, length * step)
    previous = summarize(rows[:length], source, length * step)
    comparison = {}
    for kind in KINDS:
        a, b = current[kind], previous[kind]
        comparison[kind] = (
            round((a["average_ms"] / b["average_ms"] - 1) * 100, 1)
            if (a["count"] >= 20 and b["count"] >= 20 and b["average_ms"])
            else None
        )
    slow = [json.loads(item) for item in values[-2]]
    slow = [
        item
        for item in slow
        if start <= item["timestamp"] < end
        and (source == "all" or item["source"] == source)
    ]
    first, last_http, last_worker = values[-1]
    stride = math.ceil(length / 120)
    trend = []
    for offset in range(0, length, stride):
        group = rows[length + offset : length + min(length, offset + stride)]
        observed = any(
            any(key.startswith(f"{origin}:") for key in row)
            for row in group
            for origin in (("http", "worker") if source == "all" else (source,))
        )
        trend.append(
            {
                "at": iso(start + offset * step),
                "observed": observed,
                **summarize(group, source, len(group) * step),
            }
        )
    return {
        "status": "collecting",
        "window": window,
        "source": source,
        "start": iso(start),
        "end": iso(end),
        "resolution_seconds": step,
        "first_observed_at": iso(float(first)) if first else None,
        "last_http_at": iso(float(last_http)) if last_http else None,
        "last_worker_at": iso(float(last_worker)) if last_worker else None,
        "summary": current,
        "previous": previous,
        "latency_change_percent": comparison,
        "observed_buckets": sum(
            any(
                key.startswith(f"{origin}:")
                for key in row
                for origin in (("http", "worker") if source == "all" else (source,))
            )
            for row in rows[length:]
        ),
        "total_buckets": length,
        "slow_threshold_ms": settings.DB_METRICS_SLOW_MS,
        "trend": trend,
        "slow_operations": slow,
    }
