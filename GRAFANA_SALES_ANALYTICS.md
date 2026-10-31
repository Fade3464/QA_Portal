# CallLens Grafana Sales Analytics

CallLens exposes a company-wide Grafana sidecar at `/analytics/`. Grafana never connects to PostgreSQL directly. Its provisioned Infinity datasource calls the bearer-protected aggregate endpoint `GET /api/v1/analytics/grafana/sales/`.

## Business definitions

- **SALE opportunities**: calls whose VICIdial disposition is `SALE`.
- **Sold**: `SALE` calls where the manually maintained `sold` flag is true.
- **Transfers**: `SALE` calls where `sold` is false. A dialer `SALE` never automatically marks a policy sold.
- **Agent Leaderboard conversion**: `(Transfers + Sold) / all non-provisional call records for that agent in the selected time range × 100`. This definition is leaderboard-only; Team, Project, Client, and summary conversion definitions are unchanged.
- **20+ / 30+**: the manually maintained client-side duration flags.
- **Missing preset**: a `SALE` whose User Stats preset lookup did not resolve a preset.
- **Stale calls**: provisional calls that exceeded the two-hour Start/Dispo lifecycle window.

## Dashboard

The provisioned `CallLens Sales Performance` dashboard is designed as a team-facing performance view rather than a raw metrics wall. It opens on **today so far** (`now/d` → `now`) and refreshes every minute. Grafana's native **Projects** selector supports multi-select plus **All**; Team and Client/Preset remain single-select to keep the primary filtering flow simple. Every panel uses the same selected time range and filters.

The layout is intentionally outcome-first:

- The top **Performance snapshot** is deliberately limited to six useful KPIs: **Sold**, **30+ Calls**, **Transfers**, **Conversion**, **30+ → Sold**, and **Below 20 min**. Redundant diagnostic KPI cards were removed from the primary view so the dashboard reads like a performance board rather than a telemetry wall.
- Stat panels show only the value beneath the Grafana panel title; duplicate in-card labels are removed. Color is used as emphasis rather than decoration: Sold is green, 30+ is purple, Transfers is orange, and Conversion is performance-threshold colored in tables.
- **Performance over time** and **Outcome mix** focus on the same core volume story: Sold, 30+, and Transfers. Short ranges use hourly buckets and longer ranges use daily buckets.
- **Top sellers** remains the fast visual ranking. The Agent leaderboard keeps the underlying **Agent → Team leader → Sold → 30+ → Transfers → Conversion %** data order and defaults to Team leader A→Z with Sold descending inside each leader group, but the Sold field is hidden in the table by default to reduce horizontal clutter while remaining available to the sort logic. Team Performance uses **Team → Team leader → Sold → 30+ → Transfers → Conversion %** and keeps its Sold-descending ranking. Project and Client remain **Entity → Sold → 30+ → Transfers → Conversion %**.
- Agent leaderboard membership comes from finalized/stale agent-attributed call records in the selected time/team/project scope, not only SALE rows. Provisional `NEW` (and legacy `INCALL`) live-call rows are excluded entirely. Agents with completed non-SALE activity therefore remain visible with zero Sold/30+/Transfers/Conversion values; choosing a Client/Preset changes their SALE metrics but does not remove otherwise-active agents from the leaderboard.
- When **Client / preset = All**, Agent Leaderboard and Team Performance dynamically insert one column for every resolved preset visible in the selected time/project/team scope. Each dynamic preset cell is that agent/team's transfer count for the preset. Selecting one client removes the dynamic preset columns again.
- Table widths and panel heights are tuned for fast scanning: ownership columns get useful space, numeric performance fields are compact and centered, oversized empty panel areas are reduced, and Grafana-native colored cell types reinforce the important metrics without filling the page with decoration.
- Performance tables are tall enough to keep roughly seven compact rows visible before scrolling.
- The old full-width **Sold in selected time range** stat card was removed because it duplicated the Sold KPI. The bottom drill-down is **Sales and 30+** with Agent, Team, Number, Client, Sale Status, Client status, and Disposition time. It contains every sold SALE call plus unsold SALE calls whose manual `client_30_plus` flag is true. `Sale Status` is `Confirmed` for sold calls and 'Only 30+` for qualifying unsold 30+ calls. The Client value comes from the resolved SALE preset/client field.

Project multi-select is implemented end-to-end: Grafana emits one `project=...` query parameter per selected project and the analytics service treats the selected names as an OR filter. The custom `__all` value removes the project restriction without expanding every project into a very long URL. The backend caches each aggregate response for 60 seconds and filter metadata for five minutes, so multiple Grafana panels reuse the same Redis-backed payload rather than repeatedly scanning the calls table.

The aggregate analytics payload excludes recordings and lead metadata. The internal **Sales and 30+** and **Transfer calls** drill-downs intentionally include the call phone number because authorized dashboard users need to locate business-relevant entries inside the currently selected time window.

## Administration

Edit the company under **Administration → Companies** and enable **Sales analytics / Grafana**. Set the shared viewer username/password employees should use. Only one company can have sales analytics enabled in a portal deployment. The password is encrypted at rest and synchronized to Grafana by Celery.

The internal Grafana service administrator is separate from the viewer and is configured only through `.env`:

```env
GRAFANA_SERVICE_ADMIN_USER=calllens_grafana_admin
GRAFANA_SERVICE_ADMIN_PASSWORD=<strong-random-secret>
GRAFANA_ANALYTICS_API_TOKEN=<another-long-random-secret>
GRAFANA_RENDERER_TOKEN=<separate-long-random-renderer-secret>
GRAFANA_ROOT_URL=https://calllens.example.com/analytics/
GRAFANA_COOKIE_SECURE=true
```

`GRAFANA_SERVICE_ADMIN_PASSWORD`, `GRAFANA_ANALYTICS_API_TOKEN`, and `GRAFANA_RENDERER_TOKEN` must not be shared with users.

## Image rendering / panel exports

Grafana 13 no longer supports the historical in-process Image Renderer plugin. This repository therefore runs the supported `grafana/grafana-image-renderer:v5.12.10` service on the private Compose network and connects Grafana to it with `GF_RENDERING_SERVER_URL`, `GF_RENDERING_CALLBACK_URL`, and a matching renderer authentication token. No renderer port is published publicly.

With the renderer healthy, Grafana can render dashboard/panel views (including table panels) as images through Grafana's normal share/render workflow. The renderer uses the internal callback `http://grafana:3000/analytics/`, which matches this deployment's configured Grafana subpath.

## Deployment

```bash
docker compose build backend worker beat frontend
docker compose pull grafana renderer
docker compose run --rm --no-deps -e DB_DIRECT=true --entrypoint python backend manage.py migrate --noinput
docker compose up -d --no-deps --wait backend
docker compose up -d --no-deps worker beat
docker compose up -d renderer
docker compose up -d --wait grafana
docker compose up -d --no-deps --wait frontend
```

The first Grafana start downloads the pinned Infinity datasource plugin. The image renderer is a separate service (not a Grafana plugin in Grafana 13). After Grafana becomes healthy, the viewer sync task converges the Administration-configured credentials.

## Internal HTTP / HTTPS handling

Grafana reaches CallLens over the private Docker network at `http://backend:8000`. Production Django keeps `SECURE_SSL_REDIRECT` enabled for normal traffic, but the bearer-protected Grafana analytics path is listed in `SECURE_REDIRECT_EXEMPT` so the internal HTTP request is not redirected to `https://backend:8000`. Public access to `/api/v1/analytics/grafana/` remains blocked by the frontend/Nginx layer.

The provisioned Infinity datasource also sends `X-Forwarded-Proto: https` as defense in depth. Do not disable `SECURE_SSL_REDIRECT` globally.

Infinity 4.x query column selectors must be strings. The provisioned `Missing preset` and `Stale calls` panels use `missing_preset` and `stale_calls` respectively.


Dynamic preset columns in Agent Leaderboard and Team Performance are always appended after **Conversion %**. Grafana explicitly pins the fixed fields before allowing auto-discovered preset columns.

The dashboard also includes a final **Transfer calls** table with Agent, Team, Number, Client, Client status, and Disposition time. It follows the active dashboard filters and exposes native column filters on every heading.

- **Transfer call details** is a separate dashboard section below **Sold call details**; it is not nested under the Sold section.

- The Agent Leaderboard Team leader column is filterable using Grafana's native table-column filter.

### CSV export limitation

Grafana's CSV export contains table data, not visual presentation metadata. CSV itself cannot encode cell fills, font weight, borders, heatmaps, or CSS-based table styling. Use Grafana's rendered image export when the visual styling must be preserved. If an editable styled spreadsheet is required, it must be exported as a spreadsheet format such as XLSX rather than CSV.

## Styled Excel exports

The backend still supports authenticated styled XLSX generation for internal use, but the dashboard does not inject custom XLSX export buttons or links. Native Grafana export behavior remains unchanged.

The XLSX export mirrors the visible table semantics:

- Agent Leaderboard keeps the hidden Sold field out of the workbook, preserves Team Leader ordering, reproduces 30+ / Transfer / Conversion styling, applies heatmaps to dynamic preset columns, and writes the cumulative footer as a bold final row.
- Team, Project and Client performance exports preserve the Sold/30+/Transfer/Conversion visual treatment; dynamic preset columns are included for Team when Client/Preset is All.
- Sales and 30+ exports include the Sale Status field and do not apply special phone-number cell highlighting.
- Transfer exports keep the same six visible columns.
- All worksheets include Excel header styling, frozen headers, column filters, sensible widths and native percentage/date number formats.

Grafana's original CSV export remains available and unchanged. CSV is intentionally data-only because the CSV format cannot represent cell fills, fonts, borders or other visual formatting.

### Styled XLSX exports

The authenticated `/analytics/export/sales.xlsx` backend route remains available for internal integrations, but no custom dashboard-level or panel-level XLSX links are provisioned.
