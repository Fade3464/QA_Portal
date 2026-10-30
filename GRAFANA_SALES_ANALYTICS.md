# CallLens Grafana Sales Analytics

CallLens exposes a company-wide Grafana sidecar at `/analytics/`. Grafana never connects to PostgreSQL directly. Its provisioned Infinity datasource calls the bearer-protected aggregate endpoint `GET /api/v1/analytics/grafana/sales/`.

## Business definitions

- **SALE opportunities**: calls whose VICIdial disposition is `SALE`.
- **Sold**: `SALE` calls where the manually maintained `sold` flag is true.
- **Transfers**: `SALE` calls where `sold` is false. A dialer `SALE` never automatically marks a policy sold.
- **20+ / 30+**: the manually maintained client-side duration flags.
- **Missing preset**: a `SALE` whose User Stats preset lookup did not resolve a preset.
- **Stale calls**: provisional calls that exceeded the two-hour Start/Dispo lifecycle window.

## Dashboard

The provisioned `CallLens Sales Performance` dashboard is designed as a team-facing performance view rather than a raw metrics wall. It opens on **today so far** (`now/d` → `now`) and refreshes every minute. Grafana's native **Projects** selector supports multi-select plus **All**; Team and Client/Preset remain single-select to keep the primary filtering flow simple. Every panel uses the same selected time range and filters.

The layout is intentionally outcome-first:

- **Sold** is the first and most visually prominent KPI. The old standalone **SALE opportunities** card is removed.
- Secondary KPI cards explain conversion, transfers, call-duration milestones, preset health and stale calls. Hover descriptions define each metric for new users.
- **Sales movement over time** automatically uses hourly buckets for today/short ranges and daily buckets for longer ranges; a native Grafana bar gauge adds quick outcome context without requiring users to read a table first.
- **Top sellers** and the detailed **Agent leaderboard** make peer performance immediately visible, followed by Team, Project and Client/Preset breakdowns. Tables default to **Sold descending** and place Sold before supporting volume metrics.
- The dashboard closes with a full-width **Sold in selected time range** total so the final number is always visible after reviewing the breakdowns.

Project multi-select is implemented end-to-end: Grafana emits one `project=...` query parameter per selected project and the analytics service treats the selected names as an OR filter. The custom `__all` value removes the project restriction without expanding every project into a very long URL. The backend caches each aggregate response for 60 seconds and filter metadata for five minutes, so multiple Grafana panels reuse the same Redis-backed payload rather than repeatedly scanning the calls table.

No phone numbers, recording URLs, lead details or customer PII are returned by the analytics API.

## Administration

Edit the company under **Administration → Companies** and enable **Sales analytics / Grafana**. Set the shared viewer username/password employees should use. Only one company can have sales analytics enabled in a portal deployment. The password is encrypted at rest and synchronized to Grafana by Celery.

The internal Grafana service administrator is separate from the viewer and is configured only through `.env`:

```env
GRAFANA_SERVICE_ADMIN_USER=calllens_grafana_admin
GRAFANA_SERVICE_ADMIN_PASSWORD=<strong-random-secret>
GRAFANA_ANALYTICS_API_TOKEN=<another-long-random-secret>
GRAFANA_ROOT_URL=https://calllens.example.com/analytics/
GRAFANA_COOKIE_SECURE=true
```

`GRAFANA_SERVICE_ADMIN_PASSWORD` and `GRAFANA_ANALYTICS_API_TOKEN` must not be shared with users.

## Deployment

```bash
docker compose build backend worker beat frontend
docker compose pull grafana
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate --noinput
docker compose up -d --no-deps --wait backend
docker compose up -d --no-deps worker beat
docker compose up -d --wait grafana
docker compose up -d --no-deps --wait frontend
```

The first Grafana start downloads the pinned Infinity datasource plugin. After it becomes healthy, the viewer sync task converges the Administration-configured credentials.

## Internal HTTP / HTTPS handling

Grafana reaches CallLens over the private Docker network at `http://backend:8000`. Production Django keeps `SECURE_SSL_REDIRECT` enabled for normal traffic, but the bearer-protected Grafana analytics path is listed in `SECURE_REDIRECT_EXEMPT` so the internal HTTP request is not redirected to `https://backend:8000`. Public access to `/api/v1/analytics/grafana/` remains blocked by the frontend/Nginx layer.

The provisioned Infinity datasource also sends `X-Forwarded-Proto: https` as defense in depth. Do not disable `SECURE_SSL_REDIRECT` globally.

Infinity 4.x query column selectors must be strings. The provisioned `Missing preset` and `Stale calls` panels use `missing_preset` and `stale_calls` respectively.
