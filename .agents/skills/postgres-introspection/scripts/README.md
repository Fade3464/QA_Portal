# Introspection scripts: reference implementation

This is a working reference implementation that introspects a PostgreSQL database into committed files. It is a worked example of the method, not files to drop in unchanged. Read `../references/reference-implementation.md` first for how to adapt it to the target repository's stack, and treat copying verbatim as correct only when the host repository is already a Node and TypeScript project. The scripts adjust to any PostgreSQL database through auto-discovery and a few environment variables.

## Files

The pipeline is one stage per file, in the order it runs.

`database.ts` is the orchestrator: connect, build the model, render, write.

`lib/db.ts` holds the read-only connection, schema discovery, the migration-version reader, and the Postgres array normalizer.

`lib/catalog.ts` holds the catalog queries, one function per object kind.

`lib/model.ts` assembles the table-centric model from the catalog rows.

`lib/render.ts` renders the complete document and the per-object files.

`lib/output.ts` holds the file writers and the Markdown table and heading helpers.

`cluster.ts` is a second, optional subject: the PostgreSQL instance (server, roles, databases, tablespaces, extensions, non-default settings). Its output is environment-specific, so it is generated on demand and git-ignored.

`pgbouncer.ts` is a third subject: the connection pooler, read through its admin `SHOW` interface over the wire protocol. Its output is environment-specific and live, so it is generated on demand and git-ignored. It needs a PgBouncer admin or stats user and connects via `PGBOUNCER_ADMIN_URL`.

`postgrest.ts` is a fourth subject, over HTTP rather than the wire protocol via `lib/http.ts`. It downloads the served OpenAPI to a committed, normalized `state/postgrest-openapi.json`, and writes an on-demand, git-ignored report with admin health and a reconciliation against the `api` schema in `state/database.json`. It connects via `POSTGREST_URL` and `POSTGREST_ADMIN_URL` and never reads the JWT secret.

## Dependencies

The scripts need `pg` at runtime and `tsx` to run the TypeScript directly. Node 22 or newer is assumed.

```bash
npm install --save pg
npm install --save-dev tsx @types/pg @types/node typescript
```

## Configuration

Schemas are discovered from the catalog, not hard-coded. Every non-system schema is reported; the `pg_` family and the information schema are excluded, and objects owned by an extension are skipped. Pin an explicit set with `INTROSPECT_SCHEMAS`, a comma-separated list, or drop names with `INTROSPECT_EXCLUDE_SCHEMAS`.

The migration version stamp is detected from known tables, `public.schema_migrations` for dbmate and Rails and `public.flyway_schema_history` for Flyway. Override the table with `INTROSPECT_VERSION_TABLE`. If none is found the stamp is `unknown`, which is not fatal.

The connection comes from `DATABASE_URL`. The fallback in `lib/db.ts` points at the source project's local port and should be replaced or overridden in another repository.

## Wiring

Add an npm script that runs the orchestrator with `tsx`.

```json
{
  "scripts": {
    "introspect:database": "tsx path/to/database.ts"
  }
}
```

## Running

Run against a fully migrated database, not a working database that may carry ad-hoc changes, so the output reflects the migrations and not local drift. Point at an existing migrated dev, test, or CI database; never reset or recreate a database to produce one.

```bash
DATABASE_URL=postgres://user:pass@localhost:5432/app npm run introspect:database
```

## Output and version control

The generator writes `state/database.json` (the navigable JSON), `state/database.md` (the complete document), and one self-contained file per table, view, and function under `state/database/`. Commit the two root files. Git-ignore the per-object tree (`state/database/`), since it duplicates the JSON and the complete document and would add noise to every diff. Git-ignore the cluster and pgbouncer outputs (`state/cluster.*` and `state/pgbouncer.*`) entirely, since they are environment-specific. Git-ignore the postgrest report (`state/postgrest.json`, `state/postgrest.md`) but commit the downloaded OpenAPI (`state/postgrest-openapi.json`).
