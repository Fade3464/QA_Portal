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

The provisioned `CallLens Sales Performance` dashboard contains KPI cards, daily trend, Team/Team Leader performance, client/preset performance, project performance, and an agent leaderboard. Project, Team and Client/Preset selectors sit above the dashboard alongside Grafana's native date/time picker. It refreshes every minute. The backend caches each aggregate response for 60 seconds and filter metadata for five minutes, so multiple Grafana panels reuse the same Redis-backed payload rather than repeatedly scanning the calls table.

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
