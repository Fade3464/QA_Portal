import { Client } from 'pg';
import { code, heading, markdownTable, writeStateJson, writeStateText } from './lib/output.js';

// PgBouncer introspection: the connection pooler in front of PostgreSQL. Reports its effective
// configuration and its live pool health by querying the admin interface over the PostgreSQL
// wire protocol (the special `pgbouncer` admin database and its SHOW commands).
//
// The output is environment-specific (config) and volatile (runtime counters), so
// state/pgbouncer.json and state/pgbouncer.md are generated on demand and git-ignored, not
// committed. The subject is one file because the model is small.
//
// The admin database does not support transactions, so this uses a plain connection rather
// than the read-only-transaction helper.

// Replace this fallback, or always set PGBOUNCER_ADMIN_URL, when adapting these scripts.
// It points at a local PgBouncer admin interface and is only a convenience for the example.
const defaultAdminUrl = 'postgres://pgbouncer:pgbouncer@localhost:6432/pgbouncer';

async function main(): Promise<void> {
  const client = new Client({ connectionString: process.env['PGBOUNCER_ADMIN_URL'] ?? defaultAdminUrl });
  await client.connect();
  try {
    const model = await buildModel(client);
    writeStateJson('pgbouncer.json', model);
    writeStateText('pgbouncer.md', renderModel(model));
    console.log('Wrote state/pgbouncer.json and state/pgbouncer.md (on-demand snapshot, not committed).');
  } finally {
    await client.end();
  }
}

type Row = Record<string, unknown>;

interface PgBouncerModel {
  subject: 'pgbouncer';
  config: {
    settings: Record<string, unknown>;
    databases: Record<string, Row>;
    users: Record<string, Row>;
  };
  runtime: {
    pools: Row[];
    stats: Row[];
    lists: Record<string, unknown>;
  };
}

async function show(client: Client, command: string): Promise<Row[]> {
  const result = await client.query<Row>(command);
  // Defensive: never carry a column literally named password, even though SHOW does not expose one.
  return result.rows.map((row) => {
    const copy: Row = {};
    for (const [key, value] of Object.entries(row)) {
      if (key.toLowerCase() !== 'password') copy[key] = value;
    }
    return copy;
  });
}

function keyBy(rows: Row[], field: string): Record<string, Row> {
  const out: Record<string, Row> = {};
  for (const name of rows.map((row) => String(row[field])).sort()) {
    const row = rows.find((candidate) => String(candidate[field]) === name);
    if (row === undefined) continue;
    const rest: Row = {};
    for (const [key, value] of Object.entries(row)) {
      if (key !== field) rest[key] = value;
    }
    out[name] = rest;
  }
  return out;
}

async function buildModel(client: Client): Promise<PgBouncerModel> {
  const config = await show(client, 'SHOW CONFIG');
  const databases = await show(client, 'SHOW DATABASES');
  const users = await show(client, 'SHOW USERS');
  const pools = await show(client, 'SHOW POOLS');
  const stats = await show(client, 'SHOW STATS');
  const lists = await show(client, 'SHOW LISTS');

  const settings: Record<string, unknown> = {};
  for (const row of config
    .map((r) => ({ key: String(r['key']), value: r['value'] }))
    .sort((a, b) => a.key.localeCompare(b.key))) {
    settings[row.key] = row.value;
  }

  return {
    subject: 'pgbouncer',
    config: {
      settings,
      databases: keyBy(databases, 'name'),
      users: keyBy(users, 'name'),
    },
    runtime: {
      pools: sortRows(pools, ['database', 'user']),
      stats: sortRows(stats, ['database']),
      lists: Object.fromEntries(lists.map((row) => [String(row['list']), row['items']])),
    },
  };
}

function sortRows(rows: Row[], by: string[]): Row[] {
  return [...rows].sort((a, b) => by.map((f) => String(a[f]).localeCompare(String(b[f]))).find((c) => c !== 0) ?? 0);
}

function renderModel(model: PgBouncerModel): string {
  const lines: string[] = [];
  lines.push('# pgbouncer');
  lines.push('');
  lines.push('Generated artifact. Do not edit by hand. Regenerate with `npm run introspect:pgbouncer`.');
  lines.push('');
  lines.push(
    'This is an on-demand snapshot of the running connection pooler. It answers how the pooler is configured, for orientation when connecting to an unfamiliar environment, not live monitoring. The configuration is environment-specific and the runtime section is a single sample, so it is not committed; for ongoing pool and query debugging use a live admin connection or a metrics stack.',
  );

  lines.push('');
  lines.push(heading(2, 'config'));

  lines.push('');
  lines.push(heading(3, 'databases'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Name', 'Host', 'Port', 'Database', 'Pool mode', 'Pool size', 'Max conns', 'Current conns'],
      Object.entries(model.config.databases).map(([name, row]) => [
        code(name),
        cell(row['host']),
        cell(row['port']),
        cell(row['database']),
        cell(row['pool_mode']),
        cell(row['pool_size']),
        cell(row['max_connections']),
        cell(row['current_connections']),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(3, 'users'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Name', 'Pool mode', 'Current connections'],
      Object.entries(model.config.users).map(([name, row]) => [
        code(name),
        cell(row['pool_mode']),
        cell(row['current_connections']),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(3, 'settings'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Setting', 'Value'],
      Object.entries(model.config.settings).map(([key, value]) => [code(key), cell(value)]),
    ),
  );

  lines.push('');
  lines.push(heading(2, 'runtime'));
  lines.push('');
  lines.push('A single sample of live telemetry at generation time, for orientation only, not monitoring.');

  lines.push('');
  lines.push(heading(3, 'pools'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Database', 'User', 'Clients active', 'Clients waiting', 'Servers active', 'Servers idle', 'Max wait'],
      model.runtime.pools.map((row) => [
        cell(row['database']),
        cell(row['user']),
        cell(row['cl_active']),
        cell(row['cl_waiting']),
        cell(row['sv_active']),
        cell(row['sv_idle']),
        cell(row['maxwait']),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(3, 'stats'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Database', 'Transactions', 'Queries', 'Avg query time (us)', 'Avg wait time (us)'],
      model.runtime.stats.map((row) => [
        cell(row['database']),
        cell(row['total_xact_count']),
        cell(row['total_query_count']),
        cell(row['avg_query_time']),
        cell(row['avg_wait_time']),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(3, 'lists'));
  lines.push('');
  lines.push(
    markdownTable(
      ['List', 'Items'],
      Object.entries(model.runtime.lists).map(([list, items]) => [code(list), cell(items)]),
    ),
  );

  return lines.join('\n');
}

function cell(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

await main();
