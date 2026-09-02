import type { Client } from 'pg';
import { closeReadOnly, connectReadOnly } from './lib/db.js';
import { fetchExtensions } from './lib/catalog.js';
import { code, heading, markdownTable, writeStateJson, writeStateText } from './lib/output.js';

// Cluster introspection: the PostgreSQL instance one level up from the database. Reports the
// server, the role inventory, the databases and tablespaces, the installed extensions, and the
// non-default settings. Read-only.
//
// Unlike the database subject, this output is environment-specific (settings and roles vary by
// deployment and change at runtime), so state/cluster.json and state/cluster.md are generated
// on demand and git-ignored, not committed. The subject is one file because the model is small.

async function main(): Promise<void> {
  const client = await connectReadOnly();
  try {
    const model = await buildCluster(client);
    writeStateJson('cluster.json', model);
    writeStateText('cluster.md', renderCluster(model));
    console.log('Wrote state/cluster.json and state/cluster.md (on-demand snapshot, not committed).');
  } finally {
    await closeReadOnly(client);
  }
}

interface ClusterModel {
  subject: 'cluster';
  server: { version: string; 'version-num': number; encoding: string };
  extensions: Record<string, string>;
  roles: Record<string, RoleModel>;
  databases: Record<string, { owner: string; encoding: string; collation: string; ctype: string }>;
  tablespaces: Record<string, { owner: string }>;
  settings: {
    'non-default': Array<{ name: string; setting: string; unit: string | null; source: string; category: string }>;
  };
}

interface RoleModel {
  login: boolean;
  superuser: boolean;
  createrole: boolean;
  createdb: boolean;
  replication: boolean;
  'connection-limit': number;
  'has-password': boolean;
  'valid-until': string | null;
}

async function buildCluster(client: Client): Promise<ClusterModel> {
  // noinspection SqlNoDataSourceInspection
  const server = await client.query<{ version: string; num: string; encoding: string }>(
    `select version() as version,
            current_setting('server_version_num') as num,
            current_setting('server_encoding') as encoding`,
  );
  const row = server.rows[0];

  // noinspection SqlNoDataSourceInspection
  const roles = await client.query<{
    name: string;
    login: boolean;
    superuser: boolean;
    createrole: boolean;
    createdb: boolean;
    replication: boolean;
    connLimit: number;
    hasPassword: boolean;
    validUntil: Date | string | null;
  }>(
    `select rolname as name, rolcanlogin as login, rolsuper as superuser, rolcreaterole as createrole,
            rolcreatedb as createdb, rolreplication as replication, rolconnlimit as "connLimit",
            (rolpassword is not null) as "hasPassword", rolvaliduntil as "validUntil"
       from pg_roles where rolname not like 'pg\\_%' order by rolname`,
  );

  // noinspection SqlNoDataSourceInspection
  const databases = await client.query<{
    name: string;
    owner: string;
    encoding: string;
    collate: string;
    ctype: string;
  }>(
    `select d.datname as name, pg_get_userbyid(d.datdba) as owner, pg_encoding_to_char(d.encoding) as encoding,
            d.datcollate as collate, d.datctype as ctype
       from pg_database d where not d.datistemplate order by d.datname`,
  );

  // noinspection SqlNoDataSourceInspection
  const tablespaces = await client.query<{ name: string; owner: string }>(
    `select spcname as name, pg_get_userbyid(spcowner) as owner from pg_tablespace order by spcname`,
  );

  // noinspection SqlNoDataSourceInspection
  const settings = await client.query<{
    name: string;
    setting: string;
    unit: string | null;
    source: string;
    category: string;
  }>(
    `select name, setting, unit, source, category from pg_settings
      where source not in ('default', 'override') order by name`,
  );

  return {
    subject: 'cluster',
    server: {
      version: row?.version ?? '',
      'version-num': Number(row?.num ?? 0),
      encoding: row?.encoding ?? '',
    },
    extensions: Object.fromEntries((await fetchExtensions(client)).map((ext) => [ext.name, ext.version])),
    roles: Object.fromEntries(
      roles.rows.map((role) => [
        role.name,
        {
          login: role.login,
          superuser: role.superuser,
          createrole: role.createrole,
          createdb: role.createdb,
          replication: role.replication,
          'connection-limit': role.connLimit,
          'has-password': role.hasPassword,
          'valid-until': role.validUntil === null ? null : String(role.validUntil),
        },
      ]),
    ),
    databases: Object.fromEntries(
      databases.rows.map((db) => [
        db.name,
        { owner: db.owner, encoding: db.encoding, collation: db.collate, ctype: db.ctype },
      ]),
    ),
    tablespaces: Object.fromEntries(tablespaces.rows.map((ts) => [ts.name, { owner: ts.owner }])),
    settings: {
      'non-default': settings.rows.map((s) => ({
        name: s.name,
        setting: s.setting,
        unit: s.unit,
        source: s.source,
        category: s.category,
      })),
    },
  };
}

function renderCluster(model: ClusterModel): string {
  const lines: string[] = [];
  lines.push('# cluster');
  lines.push('');
  lines.push('Generated artifact. Do not edit by hand. Regenerate with `npm run introspect:cluster`.');
  lines.push('');
  lines.push(
    'This is an on-demand snapshot of one running PostgreSQL instance. It answers how this environment is configured, for orientation when connecting to an unfamiliar instance, not live monitoring. It is environment-specific and not committed; treat it as current, not as reproducible state.',
  );

  lines.push('');
  lines.push(heading(2, 'server'));
  lines.push('');
  lines.push(`${model.server.version}`);
  lines.push('');
  lines.push(`Encoding ${code(model.server.encoding)}. Per-database collation and ctype are in the databases section.`);

  lines.push('');
  lines.push(heading(2, 'extensions'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Extension', 'Version'],
      Object.entries(model.extensions).map(([name, version]) => [code(name), version]),
    ),
  );

  lines.push('');
  lines.push(heading(2, 'roles'));
  lines.push('');
  lines.push(
    markdownTable(
      [
        'Role',
        'Login',
        'Superuser',
        'Create role',
        'Create db',
        'Replication',
        'Conn limit',
        'Has password',
        'Valid until',
      ],
      Object.entries(model.roles).map(([name, role]) => [
        code(name),
        yesNo(role.login),
        yesNo(role.superuser),
        yesNo(role.createrole),
        yesNo(role.createdb),
        yesNo(role.replication),
        role['connection-limit'] === -1 ? 'unlimited' : String(role['connection-limit']),
        yesNo(role['has-password']),
        role['valid-until'] ?? 'none',
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(2, 'databases'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Database', 'Owner', 'Encoding', 'Collation', 'Ctype'],
      Object.entries(model.databases).map(([name, db]) => [
        code(name),
        code(db.owner),
        db.encoding,
        code(db.collation),
        code(db.ctype),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(2, 'tablespaces'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Tablespace', 'Owner'],
      Object.entries(model.tablespaces).map(([name, ts]) => [code(name), code(ts.owner)]),
    ),
  );

  lines.push('');
  lines.push(heading(2, 'settings'));
  lines.push('');
  lines.push('Settings whose source is not the built-in default. These are environment-specific.');
  lines.push('');
  lines.push(
    markdownTable(
      ['Name', 'Setting', 'Unit', 'Source', 'Category'],
      model.settings['non-default'].map((s) => [code(s.name), s.setting, s.unit ?? '', s.source, s.category]),
    ),
  );

  return lines.join('\n');
}

function yesNo(value: boolean): string {
  return value ? 'yes' : 'no';
}

await main();
