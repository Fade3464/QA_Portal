# Making the capability discoverable and current

Building the tool is not enough. A future agent will only benefit from introspection if it knows the capability exists, knows to read the state instead of reconstructing it from migrations, and trusts that the state is current. This reference covers the two things that achieve that: wiring the generation to run with migrations, and writing the capability into the repository's agent instructions.

## Wire generation to the migration run

The committed state is trustworthy only when it matches the migrations. The way to keep it matching is to regenerate it whenever migrations run, so the state is a product of the migration process rather than a thing someone remembers to refresh.

Operate on the database through migrations, not by direct calls. A schema change is a migration; running the migrations produces the new schema; regenerating the state immediately after captures it. Wire the introspection command to run right after the migration command, in whatever task runner the repository uses, so the two are one motion.

```json
{
  "scripts": {
    "migrate": "<the repository's existing migrate command>",
    "introspect:database": "<the introspection command>",
    "migrate:then:introspect": "npm run migrate && npm run introspect:database"
  }
}
```

Adapt this to the repository's actual tooling. If the repository runs migrations through a Makefile, a justfile, a shell script, or a CI step, add the introspection call to that same place. Regenerate against a fully migrated database, so the state reflects the migrations and not local drift.

Keep this wiring to the flows where migrations are meant to run: local development and continuous integration against a database built for that purpose. Wiring introspect-after-migrate must never become a reason to run migrations against a data-bearing or production database to refresh state. Refreshing the state against production is a separate, consequential action that needs the user's explicit, informed consent and a clear impact explanation, per the data-safety rules in `SKILL.md`.

The result is that after any migration runs, the state files update in the same step, and a reviewer sees the schema change and its state diff together. Over time this also makes the committed, migration-stamped state a time series: the git history becomes a reviewable record of how the database evolved, where each diff is a real change rather than noise.

## Write the capability into the agent instructions

Add a section to the repository's agent instructions file, commonly `AGENTS.md`, so future agents read the state instead of the raw dump or the migration history. Adapt the following template to the repository's actual paths, commands, and conventions.

```markdown
## Database state

The current database state is generated, not described by hand. Run the introspection command to refresh it from a fully migrated database; it reads the live catalogs read-only and writes committed files under `state/`.

Read the state instead of the raw dump or the migrations. `state/database.json` is the navigable data file queried by classification path, `state/database.md` is the complete document, and `state/database/<domain>/<kind>/<name>.md` is one self-contained file per table, view, and function.

An `UNCOMMENTED` value marks a database object that still needs a comment; it is distinct from `NONE`, which marks an absent default or an empty set. Treat `UNCOMMENTED` as a worklist. When a migration encodes a non-obvious decision, capture the essence in a single-line `COMMENT ON` in the same migration, and when the rationale is longer, keep the comment compact and point to a document with a path relative to the repository root.

Do not hand-edit anything under `state/`; it is generated. Operate on the database through migrations, and regenerate the state when migrations run.
```

If the repository covers additional layers, list each one and what it produces, and note which outputs are committed and which are generated on demand and git-ignored, so an agent knows what is available and what it must generate itself.

## Set the version-control rules

State the commit and ignore rules in the repository so the boundary is explicit. Commit the durable, portable artifacts: the navigable data file and the complete document. Git-ignore the redundant per-object tree, because it duplicates the other two and would add noise to every diff. Git-ignore the environment-specific layer outputs, such as the cluster and pooler reports, because they describe one running environment rather than the schema.

## Why discoverability is part of the deliverable

The completion criteria in `SKILL.md` include an updated agent instructions file for a reason. A capability that no future agent discovers is a capability that decays. Wiring generation into migrations keeps the state honest, and writing the capability into the agent instructions keeps it found. Together they are what make the introspection setup outlive the session that built it.
