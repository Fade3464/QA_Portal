import { cleanStateDir, code, escapeCell, heading, markdownTable, writeStateText } from './output.js';
import type { Column, FunctionModel, RoleModel, TableModel, TypeModel, ViewModel } from './model.js';

// Render the one model two ways: the complete document (every object in one file) and the
// per-object tree (one self-contained file per table, view, and function). Both come from the
// same model, so they cannot disagree. An object's facets render at a configurable level, so
// the same renderer serves the complete document (object at h4, facets at h5) and a standalone
// file (object at h1, facets at h2).

const reservedKeys = new Set(['subject', 'version', 'extensions', 'roles', 'other-objects']);

function schemaNames(artifact: Record<string, unknown>): string[] {
  return Object.keys(artifact).filter((key) => !reservedKeys.has(key));
}

function renderComment(value: string | null): string {
  return value === null ? 'UNCOMMENTED' : escapeCell(value);
}

function renderDefault(column: Column): string {
  if (column.generated === 'stored') return `generated stored: ${code(escapeCell(column.default ?? ''))}`;
  if (column.identity !== null) return `identity ${column.identity}`;
  if (column.default === null) return 'NONE';
  if (isNullLiteral(column.default)) return 'NULL';
  return code(escapeCell(column.default));
}

function isNullLiteral(expression: string): boolean {
  return (
    expression
      .replace(/::[\w ."[\]]+$/, '')
      .trim()
      .toUpperCase() === 'NULL'
  );
}

function renderGrantsBlock(grants: Record<string, string[]>): string {
  const roles = Object.keys(grants).sort();
  if (roles.length === 0) return 'NONE';
  return markdownTable(
    ['Role', 'Privileges'],
    roles.map((role) => [code(role), (grants[role] ?? []).join(', ')]),
  );
}

function pushList<T>(lines: string[], level: number, name: string, items: T[], render: (item: T) => string): void {
  lines.push('');
  lines.push(heading(level, name));
  lines.push('');
  if (items.length === 0) {
    lines.push('NONE');
  } else {
    for (const item of items) lines.push(render(item));
  }
}

export function renderTableBody(table: TableModel, facetLevel: number): string[] {
  const lines: string[] = [];
  lines.push('');
  lines.push(`Comment: ${renderComment(table.comment)}`);

  lines.push('');
  lines.push(heading(facetLevel, 'columns'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Column', 'Type', 'Nullable', 'Default', 'Comment'],
      table.columns.map((column) => [
        code(column.name),
        code(column.type),
        column.nullable ? 'yes' : 'no',
        renderDefault(column),
        renderComment(column.comment),
      ]),
    ),
  );

  lines.push('');
  lines.push(heading(facetLevel, 'primary-key'));
  lines.push('');
  lines.push(table['primary-key'].length === 0 ? 'NONE' : table['primary-key'].map(code).join(', '));

  pushList(
    lines,
    facetLevel,
    'foreign-keys',
    table['foreign-keys'],
    (fk) => `- ${fk.columns.map(code).join(', ')} references ${code(fk.references)} on delete ${fk['on-delete']}.`,
  );
  pushList(
    lines,
    facetLevel,
    'unique-constraints',
    table['unique-constraints'],
    (uc) => `- ${code(uc.name)}: ${uc.columns.map(code).join(', ')}.`,
  );
  pushList(
    lines,
    facetLevel,
    'check-constraints',
    table['check-constraints'],
    (ck) => `- ${code(ck.name)}: ${code(escapeCell(ck.definition))}`,
  );
  pushList(
    lines,
    facetLevel,
    'indexes',
    table.indexes,
    (ix) => `- ${code(ix.name)}: ${code(escapeCell(ix.definition))}`,
  );
  pushList(
    lines,
    facetLevel,
    'triggers',
    table.triggers,
    (tr) => `- ${code(tr.name)}: ${code(escapeCell(tr.definition))}`,
  );

  lines.push('');
  lines.push(heading(facetLevel, 'row-level-security'));
  lines.push('');
  const rls = table['row-level-security'];
  lines.push(`Row security is ${rls.enabled ? 'enabled' : 'disabled'} and ${rls.forced ? 'forced' : 'not forced'}.`);
  const policies = Object.entries(rls.policies);
  if (policies.length === 0) {
    lines.push('');
    lines.push('No policies.');
  } else {
    for (const [name, policy] of policies) {
      lines.push('');
      lines.push(heading(facetLevel + 1, name));
      lines.push('');
      lines.push(
        `A ${policy.permissive ? 'permissive' : 'restrictive'} policy for ${policy.command}, applied to ${policy.roles.map(code).join(', ')}.`,
      );
      lines.push('');
      lines.push(`Comment: ${renderComment(policy.comment)}`);
      if (policy.using !== null) {
        lines.push('');
        lines.push(`A row is visible to the command when this holds: ${code(escapeCell(policy.using))}`);
      }
      if (policy['with-check'] !== null) {
        lines.push('');
        lines.push(`A new or changed row must satisfy: ${code(escapeCell(policy['with-check']))}`);
      }
    }
  }

  lines.push('');
  lines.push(heading(facetLevel, 'grants'));
  lines.push('');
  lines.push(renderGrantsBlock(table.grants));
  return lines;
}

export function renderViewBody(view: ViewModel, facetLevel: number): string[] {
  const lines: string[] = [];
  lines.push('');
  lines.push(`Comment: ${renderComment(view.comment)}`);
  lines.push('');
  lines.push(
    `Security ${view['security-invoker'] ? 'invoker: row-level security evaluates as the caller' : 'definer: row-level security evaluates as the view owner'}.`,
  );

  lines.push('');
  lines.push(heading(facetLevel, 'columns'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Column', 'Type', 'Comment'],
      view.columns.map((column) => [code(column.name), code(column.type), renderComment(column.comment)]),
    ),
  );

  lines.push('');
  lines.push(heading(facetLevel, 'grants'));
  lines.push('');
  lines.push(renderGrantsBlock(view.grants));

  lines.push('');
  lines.push(heading(facetLevel, 'definition'));
  lines.push('');
  lines.push('```postgresql');
  lines.push('-- noinspection SqlResolveForFile');
  lines.push('');
  lines.push(view.definition);
  lines.push('```');
  return lines;
}

export function renderFunctionBody(fn: FunctionModel, facetLevel: number): string[] {
  const lines: string[] = [];
  lines.push('');
  lines.push(`Returns ${code(fn.returns)}. Volatility ${fn.volatility}. Security ${fn.security}.`);
  lines.push('');
  lines.push(`Comment: ${renderComment(fn.comment)}`);
  lines.push('');
  lines.push(`Execute roles: ${fn['execute-roles'].length === 0 ? 'NONE' : fn['execute-roles'].map(code).join(', ')}`);
  lines.push('');
  lines.push(
    'Defined by a migration. This is the live definition; the migration files hold the authoritative source and its history.',
  );

  lines.push('');
  lines.push(heading(facetLevel, 'definition'));
  lines.push('');
  lines.push('```postgresql');
  lines.push('-- noinspection SqlResolveForFile');
  lines.push('');
  lines.push(fn.definition);
  lines.push('```');
  return lines;
}

function renderTypeBody(type: TypeModel): string[] {
  const lines: string[] = [];
  lines.push('');
  lines.push(`Comment: ${renderComment(type.comment)}`);
  lines.push('');
  if (type.kind === 'enum') {
    lines.push(`Enum with values: ${(type.values ?? []).map(code).join(', ')}.`);
  } else if (type.kind === 'composite') {
    lines.push('Composite type.');
    lines.push('');
    lines.push(
      markdownTable(
        ['Field', 'Type'],
        (type.fields ?? []).map((field) => [code(field.name), code(field.type)]),
      ),
    );
  } else {
    lines.push('Domain.');
  }
  return lines;
}

export function renderComplete(artifact: Record<string, unknown>): string {
  const lines: string[] = [];
  lines.push('# database');
  lines.push('');
  lines.push('Generated artifact. Do not edit by hand. Regenerate with `npm run introspect:database`.');
  lines.push('');
  lines.push(`As of migration \`${artifact['version'] as string}\`.`);
  lines.push('');
  lines.push(
    'This is the complete state of the database in one file. The same content is in the navigable JSON `state/database.json` and split into one file per table, view, and function under `state/database/`. Headings follow the classification path, broad term first and narrowing as it descends.',
  );
  lines.push('');
  lines.push(
    'In a Default column, `NONE` means no default, `NULL` means the SQL null literal, any other default is verbatim in backticks. A comment shows `UNCOMMENTED` when none is set, distinct from `NONE`. An empty set is shown as `NONE`. A function definition is the live form; the migration files are its source and history.',
  );

  renderExtensions(lines, artifact);

  for (const schema of schemaNames(artifact)) {
    const node = artifact[schema] as Record<string, unknown>;
    lines.push('');
    lines.push(heading(2, schema));
    lines.push('');
    lines.push(`Comment: ${renderComment(node['comment'] as string | null)}`);

    renderKind(lines, node, 'tables', (name, model) => {
      lines.push(heading(4, name));
      lines.push(...renderTableBody(model as TableModel, 5));
    });
    renderKind(lines, node, 'views', (name, model) => {
      lines.push(heading(4, name));
      lines.push(...renderViewBody(model as ViewModel, 5));
    });
    renderKind(lines, node, 'functions', (name, model) => {
      lines.push(heading(4, name));
      lines.push(...renderFunctionBody(model as FunctionModel, 5));
    });
    renderKind(lines, node, 'types', (name, model) => {
      lines.push(heading(4, name));
      lines.push(...renderTypeBody(model as TypeModel));
    });
  }

  renderRoles(lines, artifact['roles'] as Record<string, RoleModel>);
  renderOtherObjects(lines, artifact['other-objects'] as Record<string, number>);

  return lines.join('\n');
}

function renderKind(
  lines: string[],
  node: Record<string, unknown>,
  kind: string,
  renderOne: (name: string, model: unknown) => void,
): void {
  const map = node[kind] as Record<string, unknown> | undefined;
  if (map === undefined) return;
  lines.push('');
  lines.push(heading(3, kind));
  for (const [name, model] of Object.entries(map)) {
    lines.push('');
    renderOne(name, model);
  }
}

function renderExtensions(lines: string[], artifact: Record<string, unknown>): void {
  const extensions = artifact['extensions'] as Record<string, string>;
  lines.push('');
  lines.push(heading(2, 'extensions'));
  lines.push('');
  lines.push(
    markdownTable(
      ['Extension', 'Version'],
      Object.entries(extensions).map(([name, version]) => [code(name), version]),
    ),
  );
}

function renderRoles(lines: string[], roles: Record<string, RoleModel>): void {
  lines.push('');
  lines.push(heading(2, 'roles'));
  for (const [name, role] of Object.entries(roles)) {
    lines.push('');
    lines.push(heading(3, name));
    lines.push('');
    const memberOf = role['member-of'].length === 0 ? 'NONE' : role['member-of'].map(code).join(', ');
    lines.push(`Can log in: ${role['can-login'] ? 'yes' : 'no'}. Member of: ${memberOf}.`);
    lines.push('');
    lines.push(`Comment: ${renderComment(role.comment)}`);
  }
}

function renderOtherObjects(lines: string[], counts: Record<string, number>): void {
  lines.push('');
  lines.push(heading(2, 'other-objects'));
  lines.push('');
  lines.push(
    'Object kinds this report does not yet capture, with their current count. A non-zero count marks a kind to add.',
  );
  lines.push('');
  lines.push(
    markdownTable(
      ['Kind', 'Count'],
      Object.entries(counts).map(([kind, count]) => [kind, String(count)]),
    ),
  );
}

// The per-object tree: one self-contained file per table, view, and function.

export function writeEntityFiles(artifact: Record<string, unknown>): void {
  cleanStateDir('database');
  const version = artifact['version'] as string;
  for (const schema of schemaNames(artifact)) {
    const node = artifact[schema] as Record<string, unknown>;

    const tables = node['tables'] as Record<string, TableModel> | undefined;
    if (tables !== undefined) {
      for (const [name, table] of Object.entries(tables)) {
        writeStateText(
          `database/${schema}/tables/${name}.md`,
          standaloneFile(`${schema}.tables.${name}`, version, renderTableBody(table, 2)),
        );
      }
    }

    const views = node['views'] as Record<string, ViewModel> | undefined;
    if (views !== undefined) {
      for (const [name, view] of Object.entries(views)) {
        writeStateText(
          `database/${schema}/views/${name}.md`,
          standaloneFile(`${schema}.views.${name}`, version, renderViewBody(view, 2)),
        );
      }
    }

    const functions = node['functions'] as Record<string, FunctionModel> | undefined;
    if (functions !== undefined) {
      const entries = Object.entries(functions);
      const baseCounts = new Map<string, number>();
      for (const [signature] of entries) {
        const base = functionBase(signature);
        baseCounts.set(base, (baseCounts.get(base) ?? 0) + 1);
      }
      const seen = new Map<string, number>();
      for (const [signature, fn] of entries) {
        const base = functionBase(signature);
        let file = base;
        if ((baseCounts.get(base) ?? 0) > 1) {
          const index = (seen.get(base) ?? 0) + 1;
          seen.set(base, index);
          file = `${base}-${index}`;
        }
        writeStateText(
          `database/${schema}/functions/${file}.md`,
          standaloneFile(`${schema}.functions.${signature}`, version, renderFunctionBody(fn, 2)),
        );
      }
    }
  }
}

// The file name for a function is its base name, kept short to avoid filesystem path limits.
// Overloads that share a base name are disambiguated with a numeric suffix; the full signature
// stays in the file's title.
function functionBase(signature: string): string {
  const open = signature.indexOf('(');
  return open === -1 ? signature : signature.slice(0, open);
}

function standaloneFile(title: string, version: string, body: string[]): string {
  return [
    `# ${title}`,
    '',
    `Generated artifact, as of migration \`${version}\`. Part of \`state/database\`; the complete document is \`state/database.md\`.`,
    ...body,
  ].join('\n');
}
