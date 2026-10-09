# QA Portal

A containerized, multi-tenant quality assurance portal for VICIdial call intake, recording retrieval, review workflows, and operational insight.

## Architecture

- **Django 5.2 LTS + Django REST Framework** for the domain, administration, and session-secured API
- **Django Channels + Redis** for authenticated branch-scoped real-time notifications
- **Celery + Redis** for durable, retryable VICIdial recording lookup and downloads
- **PostgreSQL** for companies, branches, users, dialers, calls, reviews, and audit events
- **React 19 + Ant Design 6** for the responsive portal interface
- **Nginx** for same-origin SPA, API, admin, and WebSocket routing

## First run

```bash
make setup
```

Open `.env` and replace the database, Django, and administrator passwords. Generate the dialer encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put its output in `DIALER_CREDENTIAL_KEY`, then start everything:

```bash
make up
docker compose logs -f backend worker
```

Open <http://localhost:8080>. The initial administrator comes from `ADMIN_EMAIL` and `ADMIN_PASSWORD`; it is created once and is not overwritten on later boots.

## PostgreSQL connection pooling

Docker routes web requests and Celery database traffic through an internal-only PgBouncer 1.25.1 service in transaction mode. The Celery queues, concurrency, task rate limits, retries, and row-lock claims are unchanged. Startup migrations and administrator bootstrap explicitly use PostgreSQL directly. No data volume or database schema changes are needed.

Defaults are 20 normal server connections plus 5 reserve connections (hard maximum 25 for the configured database), 200 client connections, and a 30-second pool wait timeout. Tune `PGBOUNCER_POOL_SIZE`, `PGBOUNCER_RESERVE_POOL_SIZE` (zero is allowed), `PGBOUNCER_MAX_CLIENT_CONN` (maximum 900 with the supplied file-descriptor limit), and `PGBOUNCER_QUERY_WAIT_TIMEOUT` in `.env`. Keep the server pool plus direct maintenance/other clients below PostgreSQL's `max_connections`; measure `SHOW POOLS` waiting clients before increasing limits. These defaults are a starting budget, not measured capacity.

The pooler runs non-root with a read-only filesystem, no published ports, and SCRAM authentication. Its auth file is generated from the existing database password into mode-0600 files in a private tmpfs directory; no credentials are baked into an image or written to logs. Internal traffic is not TLS-encrypted: this setup assumes a trusted single-host Docker bridge. Use TLS before moving database traffic across hosts or untrusted networks.

The generated configuration accepts database/user names containing letters, digits, underscores and hyphens (starting with a letter or underscore), and rejects newline/NUL characters in passwords. PgBouncer uses `SIGINT` with a five-minute grace period to finish active transactions on shutdown. Updating pool settings recreates this single pooler and briefly interrupts new connections; schedule that change during a quiet period. There is no transparent database failover or zero-downtime pooler upgrade in this single-instance setup.

Compose passes PostgreSQL connection fields separately, so passwords containing URL-reserved characters are supported. Native deployments may still use a percent-encoded `DATABASE_URL`; when enabling pooling there, it must describe the **direct** database, with `DB_USE_PGBOUNCER=true` and `PGBOUNCER_HOST`/`PGBOUNCER_PORT` specifying the pooler. Django uses `CONN_MAX_AGE=0`; pooled connections disable server-side cursors and automatic prepared statements. Do not add session advisory locks, `LISTEN`, persistent temporary tables, or session `SET` dependencies through the transaction pool. Transaction-local row locks and `SET LOCAL` remain supported. See [Django pooling compatibility](https://docs.djangoproject.com/en/5.2/ref/databases/#transaction-pooling-and-server-side-cursors) and [PgBouncer configuration](https://www.pgbouncer.org/config.html).

Deploy without shutting down PostgreSQL/Redis or removing volumes:

```bash
docker compose build pgbouncer backend worker
docker compose up -d --wait pgbouncer
docker compose up -d --no-deps --wait backend
docker compose up -d --no-deps worker
docker compose ps
docker compose logs --tail=100 pgbouncer backend worker
```

The backend restarts briefly during deployment; the worker retains its five-minute graceful shutdown. Existing PostgreSQL installations must already have the password in `.env`: changing `POSTGRES_PASSWORD` does **not** rotate a role password in an existing data volume.

Verify the runtime and direct routing without printing credentials:

```bash
docker compose exec -T backend python manage.py shell -c 'from django.db import connection; print(connection.settings_dict["HOST"], connection.settings_dict["PORT"]); c=connection.cursor(); c.execute("SELECT 1"); print(c.fetchone())'
docker compose exec -T -e DB_DIRECT=true backend python manage.py shell -c 'from django.db import connection; print(connection.settings_dict["HOST"], connection.settings_dict["PORT"]); c=connection.cursor(); c.execute("SELECT 1"); print(c.fetchone())'
docker compose exec -T pgbouncer sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -w -h 127.0.0.1 -p 6432 -U "$POSTGRES_USER" -d pgbouncer -c "SHOW POOLS;" -c "SHOW STATS;"'
```

Watch `cl_waiting` and `maxwait` in pools and average wait time in stats, alongside the Administration Database dashboard's latency/errors and PostgreSQL connection count. The configured application user has read-only PgBouncer `SHOW` access, not pooler admin/reload access. Run manual schema maintenance and PostgreSQL-backed tests with direct routing, e.g. `docker compose exec -T -e DB_DIRECT=true backend python manage.py migrate --noinput`. Test database creation needs a suitable PostgreSQL role and must not go through the single-database pool mapping.

Rollback routing by setting `DB_USE_PGBOUNCER=false` in `.env` and recreating only backend/worker with `docker compose up -d --no-deps backend worker`. PgBouncer can remain running but unused; never use `down -v` for this rollout or rollback.

## Administrator database performance

Open **Administration → Database** as a system administrator to view read/write query latency, approximate P95, maximum latency, queries/second, errors, historical comparisons, and sampled slow/failed operations. Filter by web requests or Celery workers and export trends as CSV. PostgreSQL health shows connections, lock waiters, cache hits, and cumulative server counters. Times are displayed in Eastern Time.

Collection uses the existing `CACHE_URL` Redis database in Docker; no database migrations, extra services, queue changes, or synthetic database benchmarks are needed. Set `DB_METRICS_ENABLED=false` to disable collection, `DB_METRICS_SLOW_MS=100` to adjust the slow-query threshold, or `DB_METRICS_REDIS_URL` to override the telemetry Redis connection. Redis failures are fail-open with short connection timeouts and a per-process 60-second circuit breaker.

History begins after deployment: minute aggregates last 48 hours and hourly aggregates 90 days. Redis persistence/backups determine durability. The UI shows completed intervals, refreshes every 30 seconds only while visible, and compares equal-length periods only when each contains at least 20 queries. P95 is a histogram upper bound, not an exact percentile. The most recent 200 slow/failed samples are retained, with a maximum of five per request/task; SQL text, parameters, exception messages, and user identifiers are never stored.

These are application SQL execution timings, including network and lock waits—not disk MB/s or end-to-end request latency. Result iteration, explicit connection commits, streaming response work, WebSocket consumers, management commands, and abruptly terminated tasks are not included. `executemany` counts as one execution. PostgreSQL block timing is shown only when `track_io_timing` is enabled; the application does not change that server setting. Query-mix changes can affect period comparisons.

Deploy with `docker compose up -d --build backend worker frontend`. Preserve the existing Redis data volume to retain history.

## Timezone policy

CallLens uses `America/New_York` for all business dates and user-facing times. This IANA timezone automatically applies EST/EDT daylight-saving transitions. Datetimes remain timezone-aware and are stored as UTC instants in PostgreSQL; the API sends offset-bearing ISO 8601 values, and the frontend converts them to Eastern Time instead of using the browser's local timezone.

Keep `TIME_ZONE=America/New_York` in every deployment. Rebuild the frontend when changing this value because its timezone is compiled into the browser bundle.

## Development tunnel

When `PRODUCTION=false`, Docker Compose starts a Cloudflare Quick Tunnel for testing VICIdial callbacks against a development machine. After the tunnel connects, its temporary public URL is written to:

```text
runtime/cloudflared-url.txt
```

Read it after startup with:

```bash
cat runtime/cloudflared-url.txt
```

The URL changes whenever the tunnel container is recreated. Quick Tunnels are intended only for development and testing. Set `PRODUCTION=true` for a production deployment; this forces Django debug mode off and HTTPS redirects on, the Cloudflare sidecar exits without opening a tunnel, and no `trycloudflare.com` host is trusted by Django.

## Configure a company and VICIdial

1. Sign into `/admin` with the system administrator to use the Ant Design administration workspace. The low-level Django fallback is available at `/django-admin/`.
2. Create a company, then a branch under it.
3. Create portal users and assign each one company, branch, and role.
4. Create a dialer under the branch. Enter its non-agent API URL/user/password, a long webhook secret, and any separate recording hostnames in the allowlist.
5. Copy the dialer's UUID shown in the admin URL.

Use this VICIdial Dispo Call URL (replace the host, UUID, and secret):

```text
VARhttps://YOUR-PORTAL/api/v1/webhooks/vicidial/DIALER_UUID/dispo/?token=WEBHOOK_SECRET&lead_id=--A--lead_id--B--&call_id=--A--call_id--B--&uniqueid=--A--uniqueid--B--&agent_log_id=--A--agent_log_id--B--&user=--A--user--B--&campaign=--A--campaign--B--&phone_number=--A--phone_number--B--&list_id=--A--list_id--B--&dispo=--A--dispo--B--&talk_time=--A--talk_time--B--&term_reason=--A--term_reason--B--&recording_id=--A--recording_id--B--&recording_filename=--A--recording_filename--B--&call_date=--A--SQLdate--B--
```

The endpoint responds immediately after the call is stored. A Celery worker performs recording lookup and download with bounded exponential retries. Duplicate webhooks are idempotent.

## Security baseline

- Passwords use Argon2 and Django's password validation.
- Authentication uses HTTP-only server sessions; no access token is stored in browser JavaScript.
- State-changing requests require CSRF tokens.
- Five failed sign-ins lock that email/IP pair for one hour.
- Every non-administrator user is constrained to one company and one branch.
- API querysets and WebSocket groups enforce branch scope on the server.
- Webhook secrets are one-way hashed; dialer API passwords are Fernet-encrypted at rest.
- Recording downloads require HTTPS, an explicit host allowlist, supported audio types, and a size cap.
- Login, logout, failures, and password reset operations are audited.

For public deployment, set `PRODUCTION=true`, configure trusted HTTPS origins/hosts, terminate TLS at the load balancer, use managed secrets, configure SMTP for password resets, and rotate the bootstrap administrator password out of the environment after first use. Production mode forces debug off and HTTPS redirects on; the edge proxy must preserve `X-Forwarded-Proto: https`.

## Retiring legacy Gmail notification delivery

Report-submission and report-return email senders have been removed. In-app and browser notifications remain active; password-reset emails still use the generic Django `EMAIL_*` transport. Remove obsolete `QA_REPORT_EMAIL_ENABLED` and `QA_RETURN_EMAIL_ENABLED` entries from deployment environments. Do not remove shared SMTP credentials if password resets use them. No replacement notification mail scheme is enabled yet.

Migration `calls.0015_remove_legacy_notification_email` removes only the old delivery status, sent timestamp, and error columns from reports/workflow events. Reports, scores, recipients, and workflow history remain. Reversing the migration recreates empty/default columns; old delivery metadata can only be recovered from a database backup.

Deploy during a maintenance window: stop old application/worker processes before applying this migration, so they cannot query removed columns or send old notifications. Build first, then back up and migrate:

```bash
docker compose build backend worker frontend
docker compose stop -t 300 backend worker
mail_removal_backup="calllens-before-mail-removal-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$mail_removal_backup"
docker compose exec -T db pg_restore --list < "$mail_removal_backup"
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate --noinput
docker compose up -d --no-deps backend worker frontend
docker compose logs --tail=100 backend worker
```

Check that the backup command succeeds and the backup is usable before migrating. Workers must restart on the new image. Previously queued `notifications.send_review_report_email` / `notifications.send_review_returned_email` messages are no longer registered and will be discarded by Celery (with an unregistered-task log); they cannot send mail. Do not purge Redis or the recording queue. Recording task limits, worker concurrency, and queue topology are unchanged.

## Checks

```bash
make test
docker compose config
```

## AI Insights V3 (experimental)

The V3 bounded investigation engine and a permanent prototype warning in the AI Insights UI are described in [AI_ARCHITECTURE_V3.md](AI_ARCHITECTURE_V3.md). Set `AI_ENGINE_VERSION=v3` **only after staging and real-Qwen validation**; the default remains `v1`. Business calculations and authorization stay within Django.

## AI Insights V2

See [`AI_ARCHITECTURE_V2.md`](AI_ARCHITECTURE_V2.md) for the provider-neutral semantic planner,
shared analytics/authorization services, migration `0003`, staging tests and
`AI_ENGINE_VERSION=v1|v2` rollout/rollback switch.


### V3 conversational analytics changes

See [AI_V3_CONVERSATIONAL_REFACTOR.md](AI_V3_CONVERSATIONAL_REFACTOR.md) for the latest V3 ranking, context and tool-use changes, bounded security model, and staging acceptance commands. V3 is a prototype and must be independently validated before management decisions.
