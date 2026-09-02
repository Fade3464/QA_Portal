# Porting the method to another database

The introspection method is database-agnostic. The reference implementation is PostgreSQL because that is where it was built and proven, but the approach in `references/approach.md` describes a way of thinking that applies to any database with an authoritative, readable, live description of its own structure. This reference explains what stays the same and what changes when the target is not PostgreSQL.

## What stays the same

The invariants do not change. Read the live source read-only. Build one model. Render it deterministically into committed files. Choose one classification path and express it identically in the data keys, the document headings, and the folder layout. Surface descriptions and mark their absence. Keep the rendered output minimal and greppable.

The output shape does not change. A single navigable data file, a single complete document, and one self-contained file per major object serve the same purpose against any database.

The completeness guard does not change in spirit. Whatever object kinds the target database has, count the ones you do not yet capture, so the tool reports its own incompleteness rather than hiding it.

The commenting practice in `references/commenting.md` applies wherever the target database can attach a comment or description to an object.

## What changes

The source of truth changes. PostgreSQL exposes its state through the `pg_` system catalogs and `information_schema`. Another engine exposes its state through its own equivalent, and you read from that equivalent instead.

The object kinds change. Map the target database's object kinds onto the same classification idea, and drop or add kinds the engine does not have or adds.

The driver quirks change. The PostgreSQL pitfalls in `references/reference-implementation.md`, such as array parsing and the grants function, are specific to PostgreSQL and its driver. Expect a different set of quirks from another engine's driver and catalog, and handle them the same way: a small normalizer at the boundary.

The version marker changes. Point the as-of stamp at whatever migration or version source the target database and its migration tool keep.

## Where to read each engine's state

MySQL and MariaDB expose structure through `information_schema` and, for some details, `SHOW` statements. The standard `information_schema` covers tables, columns, key column usage, and statistics for indexes.

SQLite exposes structure through `PRAGMA` statements such as `table_info`, `foreign_key_list`, and `index_list`, and through `sqlite_master`.

SQL Server exposes structure through `sys` catalog views and `information_schema`.

Oracle exposes structure through the data dictionary views such as `all_tables`, `all_tab_columns`, and `all_constraints`.

In every case, confirm the exact source against the target engine's current documentation before relying on it, because catalog details change across versions.

## How to proceed

Start from the method, not from the reference code. Read `references/approach.md` and design the model and the classification path for the target engine's object kinds. Then write the read-only reader against that engine's catalog, the model assembly, and the renderer in the host repository's language, reusing the structure of the reference stages as a guide.

Build the database subject first and get it deterministic before adding any layers. Then apply `references/layers.md` to whatever surrounds the target database in this deployment.
