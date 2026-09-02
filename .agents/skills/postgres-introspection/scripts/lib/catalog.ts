import type { Client } from 'pg';
import { pgArray } from './db.js';

// Catalog queries. Each function reads one kind of object from the PostgreSQL system catalogs
// for the given schemas. Objects owned by an extension are excluded, so an installed extension
// such as pg_stat_statements does not leak its tables, views, and functions into the report.

export interface SchemaComment {
  name: string;
  comment: string | null;
}

export async function fetchSchemaComments(client: Client, schemas: string[]): Promise<SchemaComment[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<SchemaComment>(
    `select n.nspname as name, obj_description(n.oid, 'pg_namespace') as comment
       from pg_namespace n where n.nspname = any($1)`,
    [schemas],
  );
  return result.rows;
}

export interface RelationComment {
  schema: string;
  name: string;
  comment: string | null;
}

export async function fetchRelationComments(client: Client, schemas: string[]): Promise<RelationComment[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<RelationComment>(
    `select n.nspname as schema, c.relname as name, obj_description(c.oid, 'pg_class') as comment
       from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind in ('r', 'v')
        and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e')`,
    [schemas],
  );
  return result.rows;
}

export interface ColumnRow {
  schema: string;
  table: string;
  column: string;
  type: string;
  nullable: boolean;
  default: string | null;
  identity: string;
  generated: string;
  comment: string | null;
}

export async function fetchColumns(client: Client, schemas: string[], relkind: 'r' | 'v'): Promise<ColumnRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<ColumnRow>(
    `select n.nspname as schema, c.relname as table, a.attname as column,
            format_type(a.atttypid, a.atttypmod) as type,
            not a.attnotnull as nullable,
            pg_get_expr(ad.adbin, ad.adrelid) as default,
            a.attidentity as identity, a.attgenerated as generated,
            col_description(c.oid, a.attnum) as comment
       from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
       join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
       left join pg_attrdef ad on ad.adrelid = c.oid and ad.adnum = a.attnum
      where n.nspname = any($1) and c.relkind = $2
        and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e')
      order by n.nspname, c.relname, a.attnum`,
    [schemas, relkind],
  );
  return result.rows;
}

export interface ConstraintRow {
  schema: string;
  table: string;
  name: string;
  type: string;
  definition: string;
  columns: string[];
  refTable: string | null;
  refColumns: string[];
  onDelete: string;
  onUpdate: string;
}

export async function fetchConstraints(client: Client, schemas: string[]): Promise<ConstraintRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<
    Omit<ConstraintRow, 'columns' | 'refColumns'> & { columns: string | string[]; refColumns: string | string[] | null }
  >(
    `select n.nspname as schema, c.relname as table, con.conname as name, con.contype as type,
            pg_get_constraintdef(con.oid) as definition,
            coalesce((
              select array_agg(att.attname order by k.ord)
                from unnest(con.conkey) with ordinality as k(attnum, ord)
                join pg_attribute att on att.attrelid = con.conrelid and att.attnum = k.attnum
            ), array[]::text[]) as columns,
            case when con.contype = 'f' then (select fn.nspname || '.' || fc.relname
                from pg_class fc join pg_namespace fn on fn.oid = fc.relnamespace where fc.oid = con.confrelid) end as "refTable",
            case when con.contype = 'f' then (select array_agg(att.attname order by k.ord)
                from unnest(con.confkey) with ordinality as k(attnum, ord)
                join pg_attribute att on att.attrelid = con.confrelid and att.attnum = k.attnum) end as "refColumns",
            con.confdeltype as "onDelete", con.confupdtype as "onUpdate"
       from pg_constraint con
       join pg_class c on c.oid = con.conrelid
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind = 'r'
      order by n.nspname, c.relname, con.contype, con.conname`,
    [schemas],
  );
  return result.rows.map((row) => ({ ...row, columns: pgArray(row.columns), refColumns: pgArray(row.refColumns) }));
}

export interface IndexRow {
  schema: string;
  table: string;
  name: string;
  unique: boolean;
  primary: boolean;
  definition: string;
}

export async function fetchIndexes(client: Client, schemas: string[]): Promise<IndexRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<IndexRow>(
    `select n.nspname as schema, c.relname as table, ic.relname as name,
            i.indisunique as unique, i.indisprimary as primary, pg_get_indexdef(i.indexrelid) as definition
       from pg_index i
       join pg_class ic on ic.oid = i.indexrelid
       join pg_class c on c.oid = i.indrelid
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind = 'r'
      order by n.nspname, c.relname, ic.relname`,
    [schemas],
  );
  return result.rows;
}

export interface TriggerRow {
  schema: string;
  table: string;
  name: string;
  definition: string;
  comment: string | null;
}

export async function fetchTriggers(client: Client, schemas: string[]): Promise<TriggerRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<TriggerRow>(
    `select n.nspname as schema, c.relname as table, t.tgname as name,
            pg_get_triggerdef(t.oid) as definition, obj_description(t.oid, 'pg_trigger') as comment
       from pg_trigger t
       join pg_class c on c.oid = t.tgrelid
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and not t.tgisinternal
      order by n.nspname, c.relname, t.tgname`,
    [schemas],
  );
  return result.rows;
}

export interface TypeRow {
  schema: string;
  name: string;
  kind: 'enum' | 'domain' | 'composite';
  values: string[] | null;
  comment: string | null;
}

export async function fetchTypes(client: Client, schemas: string[]): Promise<TypeRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<{
    schema: string;
    name: string;
    kind: TypeRow['kind'];
    values: string | string[] | null;
    comment: string | null;
  }>(
    `select n.nspname as schema, t.typname as name,
            case t.typtype when 'e' then 'enum' when 'd' then 'domain' when 'c' then 'composite' end as kind,
            case when t.typtype = 'e' then (select array_agg(e.enumlabel order by e.enumsortorder) from pg_enum e where e.enumtypid = t.oid) end as values,
            obj_description(t.oid, 'pg_type') as comment
       from pg_type t
       join pg_namespace n on n.oid = t.typnamespace
      where n.nspname = any($1)
        and (t.typtype in ('e', 'd')
             or (t.typtype = 'c' and exists (select 1 from pg_class cl where cl.oid = t.typrelid and cl.relkind = 'c')))
        and not exists (select 1 from pg_depend d where d.objid = t.oid and d.deptype = 'e')
      order by n.nspname, t.typname`,
    [schemas],
  );
  return result.rows.map((row) => ({ ...row, values: row.values === null ? null : pgArray(row.values) }));
}

export interface CompositeField {
  schema: string;
  type: string;
  column: string;
  dataType: string;
}

export async function fetchCompositeFields(client: Client, schemas: string[]): Promise<CompositeField[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<CompositeField>(
    `select n.nspname as schema, t.typname as type, a.attname as column, format_type(a.atttypid, a.atttypmod) as "dataType"
       from pg_type t
       join pg_namespace n on n.oid = t.typnamespace
       join pg_class cl on cl.oid = t.typrelid and cl.relkind = 'c'
       join pg_attribute a on a.attrelid = cl.oid and a.attnum > 0 and not a.attisdropped
      where n.nspname = any($1) and t.typtype = 'c'
      order by n.nspname, t.typname, a.attnum`,
    [schemas],
  );
  return result.rows;
}

export interface RlsPosture {
  schema: string;
  table: string;
  enabled: boolean;
  forced: boolean;
}

export async function fetchRlsPosture(client: Client, schemas: string[]): Promise<RlsPosture[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<RlsPosture>(
    `select n.nspname as schema, c.relname as table, c.relrowsecurity as enabled, c.relforcerowsecurity as forced
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind = 'r'`,
    [schemas],
  );
  return result.rows;
}

export interface PolicyRow {
  schema: string;
  table: string;
  name: string;
  command: string;
  permissive: boolean;
  roles: string[];
  using: string | null;
  withCheck: string | null;
  comment: string | null;
}

export async function fetchPolicies(client: Client, schemas: string[]): Promise<PolicyRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<Omit<PolicyRow, 'roles'> & { roles: string | string[] }>(
    `select n.nspname as schema, c.relname as table, pol.polname as name,
            pol.polcmd as command, pol.polpermissive as permissive,
            (select array_agg(rolname order by rolname) from (
               select case when ro = 0 then 'public' else pr.rolname end as rolname
                 from unnest(pol.polroles) as ro left join pg_roles pr on pr.oid = ro
            ) resolved) as roles,
            pg_get_expr(pol.polqual, pol.polrelid) as using,
            pg_get_expr(pol.polwithcheck, pol.polrelid) as "withCheck",
            obj_description(pol.oid, 'pg_policy') as comment
       from pg_policy pol
       join pg_class c on c.oid = pol.polrelid
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1)
      order by n.nspname, c.relname, pol.polname`,
    [schemas],
  );
  return result.rows.map((row) => ({ ...row, roles: pgArray(row.roles) }));
}

export interface GrantRow {
  object: string;
  role: string;
  privilege: string;
}

export async function fetchRelationGrants(client: Client, schemas: string[], roleNames: string[]): Promise<GrantRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<GrantRow>(
    `select n.nspname || '.' || c.relname as object, g.rolname as role, acl.privilege_type as privilege
       from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
       cross join lateral aclexplode(c.relacl) as acl
       join pg_roles g on g.oid = acl.grantee
      where n.nspname = any($1) and c.relkind in ('r', 'v') and g.rolname = any($2)
      order by object, g.rolname, acl.privilege_type`,
    [schemas, roleNames],
  );
  return result.rows;
}

export async function fetchRoleNames(client: Client): Promise<string[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<{ name: string }>(
    `select rolname as name from pg_roles where not rolsuper and rolname not like 'pg\\_%' order by rolname`,
  );
  return result.rows.map((row) => row.name);
}

export interface FunctionRow {
  schema: string;
  name: string;
  args: string;
  returns: string;
  security: boolean;
  volatility: string;
  comment: string | null;
  definition: string;
}

export async function fetchFunctions(client: Client, schemas: string[]): Promise<FunctionRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<FunctionRow>(
    `select n.nspname as schema, p.proname as name, pg_get_function_identity_arguments(p.oid) as args,
            pg_get_function_result(p.oid) as returns, p.prosecdef as security, p.provolatile as volatility,
            obj_description(p.oid, 'pg_proc') as comment, pg_get_functiondef(p.oid) as definition
       from pg_proc p
       join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = any($1) and p.prokind in ('f', 'p')
        and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
      order by n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)`,
    [schemas],
  );
  return result.rows;
}

export interface ExecuteGrant {
  schema: string;
  signature: string;
  role: string;
}

export async function fetchExecuteGrants(
  client: Client,
  schemas: string[],
  roleNames: string[],
): Promise<ExecuteGrant[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<ExecuteGrant>(
    `select n.nspname as schema, p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' as signature, g.rolname as role
       from pg_proc p
       join pg_namespace n on n.oid = p.pronamespace
       cross join lateral aclexplode(p.proacl) as acl
       join pg_roles g on g.oid = acl.grantee
      where n.nspname = any($1) and acl.privilege_type = 'EXECUTE' and g.rolname = any($2)
      order by signature, g.rolname`,
    [schemas, roleNames],
  );
  return result.rows;
}

export interface ViewDetail {
  schema: string;
  name: string;
  invoker: boolean;
  definition: string;
}

export async function fetchViewDetails(client: Client, schemas: string[]): Promise<ViewDetail[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<ViewDetail>(
    `select n.nspname as schema, c.relname as name,
            coalesce('security_invoker=true' = any(c.reloptions), false) as invoker,
            pg_get_viewdef(c.oid, true) as definition
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind = 'v'
        and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype = 'e')`,
    [schemas],
  );
  return result.rows;
}

export interface RoleRow {
  name: string;
  canLogin: boolean;
  memberOf: string[];
  comment: string | null;
}

export async function fetchRoles(client: Client): Promise<RoleRow[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<Omit<RoleRow, 'memberOf'> & { memberOf: string | string[] }>(
    `select r.rolname as name, r.rolcanlogin as "canLogin",
            coalesce((select array_agg(g.rolname order by g.rolname) from pg_auth_members am
                        join pg_roles g on g.oid = am.roleid where am.member = r.oid), '{}') as "memberOf",
            shobj_description(r.oid, 'pg_authid') as comment
       from pg_roles r where not r.rolsuper and r.rolname not like 'pg\\_%'
      order by r.rolname`,
  );
  return result.rows.map((row) => ({ ...row, memberOf: pgArray(row.memberOf) }));
}

export interface Extension {
  name: string;
  version: string;
}

export async function fetchExtensions(client: Client): Promise<Extension[]> {
  // noinspection SqlNoDataSourceInspection
  const result = await client.query<Extension>(
    `select extname as name, extversion as version from pg_extension order by extname`,
  );
  return result.rows;
}

// Completeness guard: count object kinds the model does not render, so the state signals when
// the schema grows a kind that is not yet captured instead of silently omitting it.
export async function fetchOtherObjectCounts(client: Client, schemas: string[]): Promise<Record<string, number>> {
  // noinspection SqlNoDataSourceInspection
  const relations = await client.query<{ kind: string; n: string }>(
    `select c.relkind as kind, count(*) as n
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = any($1) and c.relkind in ('S', 'm', 'p')
      group by c.relkind`,
    [schemas],
  );
  // noinspection SqlNoDataSourceInspection
  const eventTriggers = await client.query<{ n: string }>(`select count(*) as n from pg_event_trigger`);
  // noinspection SqlNoDataSourceInspection
  const defaultAcls = await client.query<{ n: string }>(`select count(*) as n from pg_default_acl`);

  const byKind = new Map(relations.rows.map((row) => [row.kind, Number(row.n)]));
  return {
    sequences: byKind.get('S') ?? 0,
    'materialized-views': byKind.get('m') ?? 0,
    'partitioned-tables': byKind.get('p') ?? 0,
    'event-triggers': Number(eventTriggers.rows[0]?.n ?? 0),
    'default-privileges': Number(defaultAcls.rows[0]?.n ?? 0),
  };
}
