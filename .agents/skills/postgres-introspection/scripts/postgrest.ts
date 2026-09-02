import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { getJson, getStatus } from './lib/http.js';
import { code, heading, markdownTable, writeStateJson, writeStateText } from './lib/output.js';

// PostgREST introspection: the REST layer in front of the database. Two outputs.
//
// state/postgrest-openapi.json is the served OpenAPI, committed, so the contract sits next to
// state/database.json. It is normalized for determinism: the environment-specific host,
// basePath, and schemes are stripped and keys are emitted in a stable order.
//
// state/postgrest.json and state/postgrest.md are an on-demand, git-ignored report: the
// PostgREST version, admin health, and a reconciliation of the served surface against the api
// schema already captured in state/database.json. The valuable finding is drift.
//
// The served surface mirrors the api schema, so this subject does not re-describe it; the
// artifact and the drift check are the point. The JWT secret is never read or emitted.

const apiUrl = process.env['POSTGREST_URL'] ?? 'http://localhost:3000';
const adminUrl = process.env['POSTGREST_ADMIN_URL'] ?? 'http://localhost:3001';

interface OpenApi {
  info?: { title?: string; version?: string };
  paths?: Record<string, unknown>;
  [key: string]: unknown;
}

async function main(): Promise<void> {
  const spec = (await getJson(`${apiUrl}/`, { Accept: 'application/openapi+json' })) as OpenApi;

  writeStateJson('postgrest-openapi.json', normalize(spec));

  const report = await buildReport(spec);
  writeStateJson('postgrest.json', report);
  writeStateText('postgrest.md', renderReport(report));

  console.log(
    'Wrote state/postgrest-openapi.json (committed) and state/postgrest.{json,md} (on-demand, not committed).',
  );
}

// Strip the environment-specific fields and sort keys, so the committed OpenAPI is stable.
function normalize(spec: OpenApi): unknown {
  const copy: OpenApi = structuredClone(spec);
  delete copy['host'];
  delete copy['basePath'];
  delete copy['schemes'];
  return sortDeep(copy);
}

function sortDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      out[key] = sortDeep((value as Record<string, unknown>)[key]);
    }
    return out;
  }
  return value;
}

interface Report {
  subject: 'postgrest';
  info: { title: string; version: string };
  health: { live: number; ready: number };
  reconciliation: {
    note: string;
    caveat: string;
    'function-enumeration-holds': boolean;
    'app-surface': { views: number; functions: number };
    functions: {
      'granted-not-served': string[];
      'served-not-granted-to-app': Array<{ function: string; 'execute-roles': string[] }>;
    };
    views: { 'served-without-backing': string[] };
  };
}

async function buildReport(spec: OpenApi): Promise<Report> {
  const paths = Object.keys(spec.paths ?? {});
  const servedViews = paths
    .filter((p) => /^\/[^/]+$/.test(p) && p !== '/' && !p.startsWith('/rpc'))
    .map((p) => p.slice(1));
  const servedRpcs = paths.filter((p) => p.startsWith('/rpc/')).map((p) => p.slice('/rpc/'.length));

  const db = readDatabaseState();
  const api = (db?.['api'] as Record<string, unknown> | undefined) ?? {};
  const views = (api['views'] as Record<string, { grants?: Record<string, unknown> }> | undefined) ?? {};
  const functions = (api['functions'] as Record<string, { 'execute-roles'?: string[] }> | undefined) ?? {};

  // The expected app-reachable surface is derived from app_user grants, not from the
  // anonymous OpenAPI. PostgREST lists every function in the OpenAPI regardless of role, so
  // functions can be reconciled both ways without a JWT. Views are role-gated and absent from
  // the unauthenticated OpenAPI, so only the orphan direction (served without a backing object)
  // is checkable for them.
  const baseName = (signature: string): string => signature.split('(')[0] ?? signature;
  const allViews = Object.keys(views);
  const appViews = allViews.filter((name) => 'app_user' in (views[name]?.grants ?? {}));
  const appRpcs = [
    ...new Set(
      Object.entries(functions)
        .filter(([, fn]) => (fn['execute-roles'] ?? []).includes('app_user'))
        .map(([signature]) => baseName(signature)),
    ),
  ];

  // The execute roles per function base name, so a served-but-not-app function shows which
  // roles can reach it. This is derived from the grants, no maintenance: a function with no
  // role reads as "no execute role" rather than being lumped in unexplained.
  const rolesByBase = new Map<string, Set<string>>();
  for (const [signature, fn] of Object.entries(functions)) {
    const base = baseName(signature);
    const set = rolesByBase.get(base) ?? new Set<string>();
    for (const role of fn['execute-roles'] ?? []) set.add(role);
    rolesByBase.set(base, set);
  }

  return {
    subject: 'postgrest',
    info: { title: spec.info?.title ?? '', version: spec.info?.version ?? '' },
    health: { live: await getStatus(`${adminUrl}/live`), ready: await getStatus(`${adminUrl}/ready`) },
    reconciliation: {
      note: db
        ? 'Reconciles the app-reachable surface, derived from app_user grants in state/database.json, against what PostgREST serves. No JWT is used.'
        : 'state/database.json was not found, so no reconciliation was performed.',
      caveat:
        'The OpenAPI is fetched unauthenticated. PostgREST lists every function regardless of role, so functions are reconciled both ways against app_user grants. Views are role-gated and absent from the unauthenticated OpenAPI, so only served-without-backing is checked for them.',
      // The two-way function check assumes PostgREST enumerates role-gated functions in the
      // unauthenticated OpenAPI. That holds when at least one app_user-only function is served.
      // If it ever stops holding, the function check has degraded to the views' half-blind state
      // and granted-not-served is false drift, not real; the guard makes that explicit.
      'function-enumeration-holds': appRpcs.length === 0 || appRpcs.some((f) => servedRpcs.includes(f)),
      'app-surface': { views: appViews.length, functions: appRpcs.length },
      functions: {
        'granted-not-served': appRpcs.filter((f) => !servedRpcs.includes(f)).sort(),
        'served-not-granted-to-app': servedRpcs
          .filter((f) => !appRpcs.includes(f))
          .sort()
          .map((name) => ({ function: name, 'execute-roles': [...(rolesByBase.get(name) ?? [])].sort() })),
      },
      views: {
        'served-without-backing': servedViews.filter((v) => !allViews.includes(v)).sort(),
      },
    },
  };
}

function readDatabaseState(): Record<string, unknown> | null {
  try {
    return JSON.parse(readFileSync(join(process.cwd(), 'state', 'database.json'), 'utf8')) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function renderReport(report: Report): string {
  const lines: string[] = [];
  lines.push('# postgrest');
  lines.push('');
  lines.push('Generated artifact. Do not edit by hand. Regenerate with `npm run introspect:postgrest`.');
  lines.push('');
  lines.push(
    'This is an on-demand report: the PostgREST version, admin health, and a reconciliation of the served surface against the api schema. It is environment-specific and not committed. The served contract itself is committed separately as `state/postgrest-openapi.json`.',
  );

  lines.push('');
  lines.push(heading(2, 'info'));
  lines.push('');
  lines.push(`Title ${code(report.info.title)}, version ${code(report.info.version)}.`);

  lines.push('');
  lines.push(heading(2, 'health'));
  lines.push('');
  lines.push(`Admin /live ${statusWord(report.health.live)}, /ready ${statusWord(report.health.ready)}.`);

  lines.push('');
  lines.push(heading(2, 'reconciliation'));
  lines.push('');
  lines.push(report.reconciliation.note);
  lines.push('');
  lines.push(
    `Expected app-reachable surface from grants: ${report.reconciliation['app-surface'].views} views, ${report.reconciliation['app-surface'].functions} functions.`,
  );
  lines.push('');
  lines.push(report.reconciliation.caveat);

  const fn = report.reconciliation.functions;
  lines.push('');
  lines.push(heading(3, 'functions'));
  lines.push('');
  if (!report.reconciliation['function-enumeration-holds']) {
    lines.push(
      'Warning: PostgREST does not appear to enumerate role-gated functions in the unauthenticated OpenAPI, so the function reconciliation has degraded to the views half-blind state. Treat granted-not-served below as unverified, not as real drift.',
    );
    lines.push('');
  }
  lines.push(
    fn['granted-not-served'].length === 0
      ? 'Every app_user-granted function is served.'
      : `Granted to app_user but not served (drift): ${fn['granted-not-served'].map(code).join(', ')}.`,
  );
  lines.push('');
  const notApp = fn['served-not-granted-to-app'];
  if (notApp.length === 0) {
    lines.push('Every served function is callable by app_user.');
  } else {
    lines.push(
      'Served but not callable by app_user, shown with the roles that can execute each; "no execute role" means no application role can execute it:',
    );
    lines.push('');
    for (const entry of notApp) {
      const roles =
        entry['execute-roles'].length === 0 ? 'no execute role' : entry['execute-roles'].map(code).join(', ');
      lines.push(`- ${code(entry.function)}: ${roles}`);
    }
  }

  const vw = report.reconciliation.views;
  lines.push('');
  lines.push(heading(3, 'views'));
  lines.push('');
  lines.push(
    vw['served-without-backing'].length === 0
      ? 'No view served without a backing object.'
      : `Served without a backing object (drift): ${vw['served-without-backing'].map(code).join(', ')}.`,
  );

  return lines.join('\n');
}

function statusWord(status: number): string {
  return status === 0 ? 'unreachable' : String(status);
}

await main();
