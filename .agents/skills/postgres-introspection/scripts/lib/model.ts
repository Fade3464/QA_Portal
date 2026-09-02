import type { Client } from 'pg';
import { discoverSchemas, migrationVersion } from './db.js';
import {
  fetchColumns,
  fetchCompositeFields,
  fetchConstraints,
  fetchExecuteGrants,
  fetchExtensions,
  fetchFunctions,
  fetchIndexes,
  fetchOtherObjectCounts,
  fetchPolicies,
  fetchRelationGrants,
  fetchRelationComments,
  fetchRlsPosture,
  fetchRoleNames,
  fetchRoles,
  fetchSchemaComments,
  fetchTriggers,
  fetchTypes,
  fetchViewDetails,
  type ColumnRow,
} from './catalog.js';

// Assemble the table-centric model from the catalog rows. Each schema becomes a node with its
// tables, views, functions, and types; each table carries every facet of itself in one place.
// Object keys are inserted in sorted order so the output is deterministic.

export interface Column {
  name: string;
  type: string;
  nullable: boolean;
  default: string | null;
  identity: 'always' | 'by default' | null;
  generated: 'stored' | null;
  comment: string | null;
}

export interface Policy {
  command: string;
  permissive: boolean;
  roles: string[];
  using: string | null;
  'with-check': string | null;
  comment: string | null;
}

export interface TableModel {
  comment: string | null;
  columns: Column[];
  'primary-key': string[];
  'foreign-keys': Array<{ columns: string[]; references: string; 'on-delete': string; 'on-update': string }>;
  'unique-constraints': Array<{ name: string; columns: string[] }>;
  'check-constraints': Array<{ name: string; definition: string }>;
  indexes: Array<{ name: string; definition: string }>;
  triggers: Array<{ name: string; definition: string; comment: string | null }>;
  'row-level-security': { enabled: boolean; forced: boolean; policies: Record<string, Policy> };
  grants: Record<string, string[]>;
}

export interface ViewModel {
  comment: string | null;
  columns: Array<{ name: string; type: string; comment: string | null }>;
  'security-invoker': boolean;
  definition: string;
  grants: Record<string, string[]>;
}

export interface FunctionModel {
  returns: string;
  volatility: string;
  security: 'definer' | 'invoker';
  'execute-roles': string[];
  comment: string | null;
  definition: string;
}

export interface TypeModel {
  comment: string | null;
  kind: 'enum' | 'domain' | 'composite';
  values: string[] | null;
  fields: Array<{ name: string; type: string }> | null;
}

export interface RoleModel {
  'can-login': boolean;
  'member-of': string[];
  comment: string | null;
}

const foreignKeyAction: Record<string, string> = {
  a: 'NO ACTION',
  r: 'RESTRICT',
  c: 'CASCADE',
  n: 'SET NULL',
  d: 'SET DEFAULT',
};
const policyCommand: Record<string, string> = { '*': 'ALL', r: 'SELECT', a: 'INSERT', w: 'UPDATE', d: 'DELETE' };
const volatilityLabel: Record<string, string> = { i: 'immutable', s: 'stable', v: 'volatile' };

export async function buildArtifact(client: Client): Promise<Record<string, unknown>> {
  const schemas = await discoverSchemas(client);
  const version = await migrationVersion(client);
  const roleNames = await fetchRoleNames(client);

  const schemaComments = new Map((await fetchSchemaComments(client, schemas)).map((row) => [row.name, row.comment]));
  const relationComments = new Map(
    (await fetchRelationComments(client, schemas)).map((row) => [`${row.schema}.${row.name}`, row.comment]),
  );
  const tableColumns = await fetchColumns(client, schemas, 'r');
  const viewColumns = await fetchColumns(client, schemas, 'v');
  const constraints = await fetchConstraints(client, schemas);
  const indexes = await fetchIndexes(client, schemas);
  const triggers = await fetchTriggers(client, schemas);
  const types = await fetchTypes(client, schemas);
  const compositeFields = await fetchCompositeFields(client, schemas);
  const posture = new Map((await fetchRlsPosture(client, schemas)).map((row) => [`${row.schema}.${row.table}`, row]));
  const policies = await fetchPolicies(client, schemas);
  const grants = groupGrants(await fetchRelationGrants(client, schemas, roleNames));
  const functions = await fetchFunctions(client, schemas);
  const executeGrants = await fetchExecuteGrants(client, schemas, roleNames);

  const artifact: Record<string, unknown> = { subject: 'database', version };
  artifact['extensions'] = Object.fromEntries((await fetchExtensions(client)).map((row) => [row.name, row.version]));

  for (const schema of schemas) {
    const node: Record<string, unknown> = { comment: schemaComments.get(schema) ?? null };

    const tableNames = uniqueSorted(tableColumns.filter((row) => row.schema === schema).map((row) => row.table));
    if (tableNames.length > 0) {
      const tables: Record<string, unknown> = {};
      for (const name of tableNames) {
        const key = `${schema}.${name}`;
        const tableConstraints = constraints.filter((row) => row.schema === schema && row.table === name);
        const tablePosture = posture.get(key);
        tables[name] = {
          comment: relationComments.get(key) ?? null,
          columns: tableColumns.filter((row) => row.schema === schema && row.table === name).map(toColumn),
          'primary-key': tableConstraints.find((row) => row.type === 'p')?.columns ?? [],
          'foreign-keys': tableConstraints
            .filter((row) => row.type === 'f')
            .map((row) => ({
              columns: row.columns,
              references: `${row.refTable}(${row.refColumns.join(', ')})`,
              'on-delete': foreignKeyAction[row.onDelete] ?? row.onDelete,
              'on-update': foreignKeyAction[row.onUpdate] ?? row.onUpdate,
            })),
          'unique-constraints': tableConstraints
            .filter((row) => row.type === 'u')
            .map((row) => ({ name: row.name, columns: row.columns })),
          'check-constraints': tableConstraints
            .filter((row) => row.type === 'c')
            .map((row) => ({ name: row.name, definition: row.definition })),
          indexes: indexes
            .filter((row) => row.schema === schema && row.table === name)
            .map((row) => ({ name: row.name, definition: row.definition })),
          triggers: triggers
            .filter((row) => row.schema === schema && row.table === name)
            .map((row) => ({ name: row.name, definition: row.definition, comment: row.comment })),
          'row-level-security': {
            enabled: tablePosture?.enabled ?? false,
            forced: tablePosture?.forced ?? false,
            policies: Object.fromEntries(
              policies
                .filter((row) => row.schema === schema && row.table === name)
                .map((row) => [
                  row.name,
                  {
                    command: policyCommand[row.command] ?? row.command,
                    permissive: row.permissive,
                    roles: row.roles,
                    using: row.using,
                    'with-check': row.withCheck,
                    comment: row.comment,
                  },
                ]),
            ),
          },
          grants: grants.get(key) ?? {},
        };
      }
      node['tables'] = tables;
    }

    const viewNames = uniqueSorted(viewColumns.filter((row) => row.schema === schema).map((row) => row.table));
    if (viewNames.length > 0) {
      const viewDetails = new Map((await fetchViewDetails(client, [schema])).map((row) => [row.name, row]));
      const views: Record<string, unknown> = {};
      for (const name of viewNames) {
        const detail = viewDetails.get(name);
        views[name] = {
          comment: relationComments.get(`${schema}.${name}`) ?? null,
          columns: viewColumns
            .filter((row) => row.schema === schema && row.table === name)
            .map((row) => ({ name: row.column, type: row.type, comment: row.comment })),
          'security-invoker': detail?.invoker ?? false,
          definition: (detail?.definition ?? '').trim(),
          grants: grants.get(`${schema}.${name}`) ?? {},
        };
      }
      node['views'] = views;
    }

    const schemaFunctions = functions.filter((row) => row.schema === schema);
    if (schemaFunctions.length > 0) {
      const functionMap: Record<string, unknown> = {};
      for (const fn of schemaFunctions) {
        const signature = `${fn.name}(${fn.args})`;
        functionMap[signature] = {
          returns: fn.returns,
          volatility: volatilityLabel[fn.volatility] ?? fn.volatility,
          security: fn.security ? 'definer' : 'invoker',
          'execute-roles': executeGrants
            .filter((grant) => grant.schema === schema && grant.signature === signature)
            .map((grant) => grant.role),
          comment: fn.comment,
          definition: fn.definition.trim(),
        };
      }
      node['functions'] = functionMap;
    }

    const schemaTypes = types.filter((row) => row.schema === schema);
    if (schemaTypes.length > 0) {
      const typeMap: Record<string, unknown> = {};
      for (const type of schemaTypes) {
        typeMap[type.name] = {
          comment: type.comment,
          kind: type.kind,
          values: type.values,
          fields:
            type.kind === 'composite'
              ? compositeFields
                  .filter((row) => row.schema === schema && row.type === type.name)
                  .map((row) => ({ name: row.column, type: row.dataType }))
              : null,
        };
      }
      node['types'] = typeMap;
    }

    artifact[schema] = node;
  }

  artifact['roles'] = Object.fromEntries(
    (await fetchRoles(client)).map((row) => [
      row.name,
      { 'can-login': row.canLogin, 'member-of': row.memberOf, comment: row.comment },
    ]),
  );
  artifact['other-objects'] = await fetchOtherObjectCounts(client, schemas);

  return artifact;
}

function toColumn(row: ColumnRow): Column {
  return {
    name: row.column,
    type: row.type,
    nullable: row.nullable,
    default: row.default,
    identity: row.identity === 'a' ? 'always' : row.identity === 'd' ? 'by default' : null,
    generated: row.generated === 's' ? 'stored' : null,
    comment: row.comment,
  };
}

function groupGrants(
  rows: Array<{ object: string; role: string; privilege: string }>,
): Map<string, Record<string, string[]>> {
  const byObject = new Map<string, Record<string, string[]>>();
  for (const row of rows) {
    const object = byObject.get(row.object) ?? {};
    (object[row.role] ??= []).push(row.privilege);
    byObject.set(row.object, object);
  }
  return byObject;
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right));
}
