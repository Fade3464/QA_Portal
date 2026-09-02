import { Client } from 'pg';

// Replace this fallback, or always set DATABASE_URL, when adapting these scripts to a repository.
// It points at a local development database and is only a convenience for the reference example.
const defaultConnectionString = 'postgres://postgres:postgres@localhost:5432/postgres';

// Open a connection and start a read-only transaction. Introspection never mutates the
// database it inspects; the read-only transaction enforces that at the server.
export async function connectReadOnly(): Promise<Client> {
  const client = new Client({
    connectionString: process.env['DATABASE_URL'] ?? defaultConnectionString,
  });
  await client.connect();
  await client.query('begin transaction read only');
  return client;
}

export async function closeReadOnly(client: Client): Promise<void> {
  await client.query('commit');
  await client.end();
}

// Discover the schemas to report from the catalog, rather than hard-coding them, so the same
// script describes any database. Every non-system schema is included; the pg_ family and the
// information schema are excluded. INTROSPECT_SCHEMAS pins an explicit list and
// INTROSPECT_EXCLUDE_SCHEMAS drops names, for the rare project that needs to.
export async function discoverSchemas(client: Client): Promise<string[]> {
  const include = parseList(process.env['INTROSPECT_SCHEMAS']);
  const exclude = new Set(parseList(process.env['INTROSPECT_EXCLUDE_SCHEMAS']));
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<{ nspname: string }>(
    `select nspname from pg_namespace
      where nspname <> 'information_schema' and nspname not like 'pg\\_%'
      order by nspname`,
  );
  let schemas = result.rows.map((row) => row.nspname);
  if (include.length > 0) {
    schemas = schemas.filter((name) => include.includes(name));
  }
  return schemas.filter((name) => !exclude.has(name));
}

// The applied migration version is the as-of marker stamped into every artifact. It changes
// only when the schema changes, so it carries meaning in a diff without adding noise on every
// run. The source is resilient: it tries known migration tables (and an override) and reads
// the latest version, falling back to "unknown" rather than failing on an unfamiliar tool.
export async function migrationVersion(client: Client): Promise<string> {
  const override = process.env['INTROSPECT_VERSION_TABLE'];
  const candidates = override ? [override] : ['public.schema_migrations', 'public.flyway_schema_history'];
  for (const candidate of candidates) {
    const [schema, table] = splitQualified(candidate);
    // to_regclass returns null for a missing relation without raising, so it is safe inside the
    // read-only transaction (a raised error would poison the transaction).
    const reg = await client.query<{ oid: string | null }>('select to_regclass($1) as oid', [`${schema}.${table}`]);
    if (reg.rows[0]?.oid === null || reg.rows[0]?.oid === undefined) {
      continue;
    }
    const column = await client.query<{ name: string }>(
      `select column_name as name from information_schema.columns
        where table_schema = $1 and table_name = $2 and column_name in ('version', 'installed_rank')
        order by case column_name when 'version' then 0 else 1 end limit 1`,
      [schema, table],
    );
    const versionColumn = column.rows[0]?.name;
    if (versionColumn === undefined) {
      continue;
    }
    const max = await client.query<{ value: string | null }>(
      `select max(${quoteIdent(versionColumn)})::text as value from ${quoteIdent(schema)}.${quoteIdent(table)}`,
    );
    if (max.rows[0]?.value) {
      return max.rows[0].value;
    }
  }
  return 'unknown';
}

// Normalize a Postgres array column to a string array. node-pg parses some array element
// types (text[]) but not others (name[]), in which case the value arrives as the literal
// {a,b}. This accepts either representation so callers always get an array.
export function pgArray(value: string[] | string | null): string[] {
  if (value === null || value === undefined) {
    return [];
  }
  if (Array.isArray(value)) {
    return value;
  }
  const inner = value.replace(/^\{/, '').replace(/\}$/, '');
  return inner.length === 0 ? [] : inner.split(',').map((entry) => entry.replace(/^"|"$/g, ''));
}

function parseList(value: string | undefined): string[] {
  return (value ?? '')
    .split(',')
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

function splitQualified(name: string): [string, string] {
  const dot = name.indexOf('.');
  return dot === -1 ? ['public', name] : [name.slice(0, dot), name.slice(dot + 1)];
}

function quoteIdent(identifier: string): string {
  return `"${identifier.replace(/"/g, '""')}"`;
}
