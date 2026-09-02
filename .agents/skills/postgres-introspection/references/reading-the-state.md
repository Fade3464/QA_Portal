# Reading the state

The state is rendered directly into files, so reading it needs no bespoke tool and no running database or credentials. Anyone with the committed files can read, search, and diff the schema offline, which is what lets teams and different intelligences reason about the database asynchronously. This reference shows the consumption patterns for the PostgreSQL reference output. The schema, kind, and object names in the paths reflect whatever schemas were introspected; the patterns are what transfer.

These examples assume a Unix-style shell with `cat`, `jq`, and `grep`. If the host environment lacks these, the same reads are possible through any file reader and any JSON query tool; the access pattern matters, not the specific command.

## Generate or refresh the state

The committed artifacts are usually already present. Regenerate them against a fully migrated database after a schema change, one you point at rather than one you reset to get there; see the data-safety rules in `SKILL.md`.

```bash
npm run introspect:database
```

The command prints the artifacts it wrote and the migration version it captured.

## Open a whole object

A table, view, or function is one self-contained file. This is the fastest way to get everything about one object, and the file is clean to attach to a message or paste into a review.

```bash
cat state/database/core/tables/documents.md
```

The file holds, in one place, the object comment, columns, primary key, foreign keys, unique constraints, check constraints, indexes, triggers, row-level security with each policy, and grants.

## Query the navigable data file by classification path

The data key path is the classification path, so a JSON query tool reaches any fact directly.

```bash
jq -c '.core.tables.documents."foreign-keys"[]' state/database.json
```

## List the objects of a kind

```bash
jq -r '.core.tables | keys[]' state/database.json
```

## Ask who can reach something

Grants live on the object, so an authorization question is a direct lookup rather than a search across migrations.

```bash
jq '.api.views.documents.grants' state/database.json
```

## Read a function

A function, including a row-level-security helper, is one file with its full body, so the logic behind a policy is one read away.

```bash
cat state/database/core/functions/has_project_action.md
```

Its signature, security, and execute roles are addressable in the data file.

```bash
jq -c '.core.functions["has_project_action(p_project_id uuid, p_action_code text)"] | {returns, security, "execute-roles"}' state/database.json
```

## See the database at a glance

```bash
jq '{extensions, "other-objects"}' state/database.json
```

The `other-objects` counts are the completeness guard. A non-zero count is an object kind the report does not yet capture, which is a signal to extend the tool or to record the kind as out of scope.

## Find what still needs work

An absent-comment marker in the document, or a null comment in the data file, marks an object that needs describing. The worklist is one query.

```bash
jq -r '.core.tables | to_entries | map(select(.value.comment == null)) | length' state/database.json
```

## Read the outline

Because the heading levels encode the classification path, listing the headings of the complete document is a table of contents with line numbers. An editor's structure view of the same file gives the same outline, clickable. Parsing the outline alone gives a full map of the database cheaply, without loading every object file and without touching the database, which is how a reader or tool orients before deciding what to read in full.

```bash
grep -nE '^#{1,4} ' state/database.md | head
```

## Search across the database

```bash
grep -rln 'recipient_email' state/database/
```

This finds every object file that mentions a column, expression, or role, because each file is plain text.

## Practical questions agents ask

These are worked examples of questions the state answers directly, the kind an agent reaches for during real work. They assume the PostgreSQL reference output. Adapt the field names to your model if you changed them.

A finding is the start of a judgment, not a verdict. Before you turn any of these into advice about the database, read `references/using-the-reports.md`: weigh the finding against the object's comment, the repository's documentation, and prior decisions, and defer changes to schema, security, and indexing rather than prescribing them.

### Which foreign keys are missing a covering index

An unindexed foreign key makes the referencing side of a join and cascading deletes slow. The state carries each table's foreign keys and its indexes, so the gap is computable. A foreign key is covered when some index's leading columns are exactly its columns, in order.

```bash
jq -r '
to_entries[]
| select(.value | type == "object" and has("tables"))
| .key as $schema
| .value.tables | to_entries[]
| .key as $table
| .value as $t
| ($t.indexes // [] | map(.definition | split("(")[1] | split(")")[0] | split(", "))) as $idx
| ($t["foreign-keys"] // [])[]
| . as $fk
| select(($idx | any(.[0:($fk.columns | length)] == $fk.columns)) | not)
| "\($schema).\($table): (\($fk.columns | join(", "))) -> \($fk.references)"
' state/database.json
```

This heuristic covers plain b-tree column indexes. Review expression indexes, partial indexes, opclasses, and included columns by hand, because their column lists are not simple name lists. Each line of output is a foreign key whose columns no index leads with. That is a candidate list, not a defect list: not every foreign key should be indexed, so weigh each one against the table's usage, the object's comment, and prior decisions per `references/using-the-reports.md` before recommending an index.

### Which functions are not wired into the API

In a setup where a REST layer serves the `api` schema, a function that exists in the `api` schema but is not served is not reachable. The committed OpenAPI lists the served RPC paths, and the database state lists the `api` schema functions, so the difference is the unwired set.

```bash
comm -23 \
  <(jq -r '.api.functions | keys[] | sub("\\(.*$"; "")' state/database.json | sort -u) \
  <(jq -r '.paths | keys[] | select(startswith("/rpc/")) | ltrimstr("/rpc/")' state/postgrest-openapi.json | sort -u)
```

Empty output means every `api` function is served, which is the healthy result. Any line is a function defined in the `api` schema with no served path. The PostgREST subject in `references/layers.md` automates this same reconciliation. For the broader question of which internal functions are not yet exposed in the `api` schema at all, treat that as a design judgment rather than a defect, because not every internal function should be public.

### Which tables have row-level security, and which do not

A security review starts by separating tables that enforce row-level security from tables that do not.

```bash
jq -r '
to_entries[]
| select(.value | type == "object" and has("tables"))
| .key as $schema
| .value.tables | to_entries[]
| "\(.value["row-level-security"].enabled // false)\t\($schema).\(.key)"
' state/database.json | sort
```

A table that holds private rows and shows `false` is the finding.

### Which functions run as their definer

A `SECURITY DEFINER` function runs with the privileges of its owner, so it is the part of the surface that can cross a security boundary. List them with their execute roles.

```bash
jq -r '
to_entries[]
| select(.value | type == "object" and has("functions"))
| .key as $schema
| .value.functions | to_entries[]
| select(.value.security == "definer")
| "\($schema).\(.key) [\(.value["execute-roles"] | join(", "))]"
' state/database.json
```

### What depends on a specific function or column

Because every object file is plain text, a recursive search finds every object that mentions a helper function, a column, or a role, including inside policy expressions and view definitions.

```bash
grep -rln 'current_user_id' state/database/
```

## Teaching others to read it

When you wire discoverability into the repository's agent instructions, point readers at these three access patterns: open a single object file for everything about one object, query the navigable data file by classification path for one fact, and search the per-object tree for a string across the whole database. Read `references/agents-integration.md` for the exact wording to add.
