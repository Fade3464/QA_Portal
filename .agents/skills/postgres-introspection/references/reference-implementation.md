# The reference implementation and how to adapt it

The `scripts/` directory beside this skill is a complete, runnable PostgreSQL introspection tool written in TypeScript and run through `tsx`. It is a worked example of the method in `references/approach.md`. Read it to see how each invariant becomes code, then translate it into the target repository's stack. Do not assume copying the files is the right move; copying is correct only when the host repository is already a Node and TypeScript project.

## How to use this reference

Read the reference to learn the shape of each stage, then implement that shape in the host repository's language and conventions. The catalog queries are the most directly reusable part, because they are SQL against the PostgreSQL system catalogs and do not depend on the host language. The connection handling, the model assembly, and the rendering should be written idiomatically for the host.

If the host repository is Node and TypeScript, you may adapt the files closely, adjusting the configuration points below. If the host is another language, reimplement the stages; keep the SQL, the model shape, the classification path, and the determinism rules.

## Layout

The pipeline is one file per stage, in the order it runs.

`database.ts` is the orchestrator: connect, build the model, render, write.

`lib/db.ts` holds the read-only connection, schema discovery, the migration-version reader, and the Postgres array normalizer.

`lib/catalog.ts` holds the catalog queries, one function per object kind.

`lib/model.ts` assembles the object-centric model from the catalog rows.

`lib/render.ts` renders the complete document and the per-object files.

`lib/output.ts` holds the file writers and the Markdown table and heading helpers.

`cluster.ts`, `pgbouncer.ts`, and `postgrest.ts` are optional additional subjects covered in `references/layers.md`. `lib/http.ts` is the small HTTP helper the PostgREST subject uses.

The layout is one file per pipeline stage so a reader opens the stage they care about, and a new object kind is a small change in the query, model, and render stages.

## The read-only connection

Introspection never mutates what it inspects. The connection opens a read-only transaction, and the only writes are to the output files.

```typescript
export async function connectReadOnly(): Promise<Client> {
  const client = new Client({ connectionString: process.env['DATABASE_URL'] ?? defaultConnectionString });
  await client.connect();
  await client.query('begin transaction read only');
  return client;
}
```

In the host language, do the equivalent: open a connection and begin a read-only transaction before any query.

## The as-of marker

Each artifact records the applied migration version, which changes only when the schema changes, so it carries meaning in a diff without adding noise on every run. The reference detects the version from known migration tables, `public.schema_migrations` for dbmate and Rails and `public.flyway_schema_history` for Flyway, and falls back to `unknown` rather than failing on an unfamiliar tool.

Point this at whatever version source the host repository's migration tool keeps.

## The catalog queries

State comes from the system catalogs. Columns, for example, come from `pg_attribute` joined to their defaults and comments, with `format_type` for the readable type.

```sql
select n.nspname as schema, c.relname as table, a.attname as column,
       format_type(a.atttypid, a.atttypmod) as type,
       not a.attnotnull as nullable,
       pg_get_expr(ad.adbin, ad.adrelid) as default,
       col_description(c.oid, a.attnum) as comment
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
  left join pg_attrdef ad on ad.adrelid = c.oid and ad.adnum = a.attnum
 where n.nspname = any($1) and c.relkind = $2
 order by n.nspname, c.relname, a.attnum
```

These queries are portable across PostgreSQL host languages because they are plain SQL. Read `lib/catalog.ts` for the full set, one query per object kind.

## The configuration points

Three points need adapting when the reference moves to another repository.

Schemas are discovered from the catalog, not hard-coded. Every non-system schema is reported; the `pg_` family and the information schema are excluded, and objects owned by an extension are skipped. Pin an explicit set with `INTROSPECT_SCHEMAS`, a comma-separated list, or drop names with `INTROSPECT_EXCLUDE_SCHEMAS`.

The migration version stamp is detected from known tables. Override the table with `INTROSPECT_VERSION_TABLE`. If none is found the stamp is `unknown`, which is not fatal.

The connection comes from `DATABASE_URL`. The fallback in `lib/db.ts` is a local development default and should be replaced or always overridden in another repository.

## The known pitfalls

These problems are concrete and universal enough that anyone replicating the tool for PostgreSQL will meet them. Knowing them in advance saves debugging time.

### node-pg does not parse every array type

The driver parses `text[]` into an array but returns some other array types, such as the `name[]` from `array_agg(attname)`, as the raw literal `{a,b}`. The fix is a small normalizer that accepts either form and always returns an array. The reference is `pgArray` in `lib/db.ts`. A driver in another language may have its own version of this problem; check how it returns array-typed columns.

### aclexplode rejects a column definition list

Reading grants with `aclexplode(relacl) as acl(grantor oid, grantee oid, ...)` fails with an error that a column definition list is redundant for a function with OUT parameters. The function already declares its output columns, so drop the column list and reference `acl.grantee` and `acl.privilege_type` directly.

### A formatter will fight generated files

A repository formatter that checks the whole tree will reformat generated files and break the build. Exclude generated artifacts from the formatter. Their stability comes from the generator being deterministic, not from the formatter. Check the host repository for a formatter that runs over everything before you commit generated files.

### IDEs parse fenced SQL

A view definition emitted in a fenced code block can be flagged by an IDE that parses fenced SQL. Fence it with a language identifier and open the block with a suppression comment, so a generated definition does not raise unresolved-reference warnings.

```postgresql
-- noinspection SqlResolveForFile

SELECT document_version_id, upload_id, sort FROM core.document_version_uploads link;
```

## Rendering on the classification path

A heading helper writes a level and text. The same body renderer serves the complete document, where an object sits at level 4 and its facets at level 5, and a standalone file, where the object is level 1 and its facets level 2, so the two never diverge.

```typescript
export function heading(level: number, text: string): string {
  return `${'#'.repeat(level)} ${text}`;
}
```

The Default column uses a fixed convention so a blank is never ambiguous: no default reads `NONE`, an explicit SQL null default reads `NULL`, any other default is verbatim in backticks. Carry a convention like this into the host implementation so the absence of a value is never confused with a value.

## Dependencies and wiring for the reference itself

The exact dependencies, environment variables, and the command to run the reference scripts live in `scripts/README.md`, so they stay next to the code they describe. Read that file when you run the reference as-is.

The point that matters when adapting to a host repository: create the equivalent task in whatever task runner the repository already uses, so introspection is invoked the way every other task in the repository is invoked, and wire it to run with migrations per `references/agents-integration.md`.
