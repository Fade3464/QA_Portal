# The introspection approach

This reference is the method and the vocabulary. Read it before designing or building anything. It leads with what to do, then explains why. It is written as a reusable method, not as a description of one repository.

## What introspection is

Introspection reads a live source read-only and renders its current state into files. It is generated from live reality, never hand-authored.

Keep it distinct from two neighbors. Validation asserts that live reality matches an expectation and answers yes or no. Documentation records intent and is authored by a person. The three coexist: documentation says what was meant, introspection says what is, validation says whether they agree. This skill builds introspection only. Mixing it with hand-authored content reintroduces the drift it exists to eliminate.

## The invariants

These are what separate a trustworthy introspection tool from a script that prints schema. Preserve all of them, whatever the host language.

The tool is read-only. It opens a read-only transaction, and the only writes are to the output files. It never mutates what it inspects.

The tool is sourced from the live catalogs, never from a hand-maintained list. A hand-maintained list is the drift the tool exists to eliminate.

The tool is deterministic. A rerun with no schema change produces no diff, so every diff in history is a real change. Sort every collection, insert object keys in sorted order, and stamp the artifact with the applied migration version rather than a wall-clock time.

The tool renders to files on disk, and the durable renderings are committed. Reading the state is opening or sending a file; no bespoke reader is needed. A redundant per-object tree may be rendered and git-ignored, so the committed set stays small and diffs stay quiet.

The model is built once and rendered many ways. One in-memory model feeds every rendering, so the renderings cannot disagree. Separate scripts per concern would split one object's information across outputs, the opposite of the cohesion you want.

The model is object-centric. All information about one table lives in one place: its columns, keys, constraints, indexes, triggers, row-level security policies, and grants. Nobody assembles a table from several files.

## The classification path

Every fact has one classification path, broad on the left and narrowing to the right. The same path is expressed identically in three places: the data key path, the document heading trail, and the folder path. A term the container already implies is dropped.

For the foreign keys of a documents table in a core schema, the one path is `core / tables / documents / foreign-keys`. In the navigable data file it is the key path `.core.tables.documents."foreign-keys"`. In the complete document it is the heading trail `## core`, then `### tables`, then `#### documents`, then `##### foreign-keys`. In the per-object tree it is a section of the file `state/database/core/tables/documents.md`.

Headings are short at the top and gain precision as they descend, so an editor's outline view of the complete document is a complete, clickable map of the database. Choosing one classification path and expressing it identically everywhere is the single most important design decision; it is what makes the output addressable.

The `core` and `api` terms above are illustrative, drawn from one complex setup. The leftmost segment is whatever the database's own schemas are, discovered at runtime. Every project organizes its database differently, so discover the real structure from the repository and ask the user when intent is unclear, because the people working in the repository have more insight into its design than this skill can carry. Do not impose the example layout on a database organized another way.

## Rendering discipline: keep the Markdown minimal and greppable

The rendered files follow the same discipline as well-formed authored Markdown, so they stay greppable, parseable by IDEs and tools, and reducible to an outline. Carry these rules into the renderer.

Encode structure in headings, not in decorative markup. The heading levels are the classification path, so an outline view of any file is a map of its contents. Never use bold text as a stand-in for a heading.

Keep meaning in words and structure, not in formatting. A reader using a text search, an IDE outline, or a plain parser must get the same information a human gets. Use backticks for identifiers, expressions, and code. Use tables with a header row for uniform rows of facts, and keep cells to short phrases. Fence every code or definition block with a language identifier.

Keep each file self-contained and flat. One object per file, its facets as sections, with no nested structure a tool cannot follow. The result is that a single object file is clean to attach to a message, an outline navigates the whole database, and a search for a column or role finds every object that mentions it.

## Surfacing what needs description

Object comments are surfaced wherever an object can carry one. When an object has no comment, the artifact shows a distinct marker, by convention `UNCOMMENTED`, different from the `NONE` used for an absent default or an empty set. This turns the output into a worklist of what still needs describing, rather than hiding the gap.

Treat the absent-comment marker as a worklist, not as missing data. Capturing the architect's hidden decision logic in comments is half the value of the whole method, and the discipline for it is in `references/commenting.md`.

## What the tool produces

One model is written three ways.

A single navigable data file holds everything and is queried by classification path.

A single complete document holds the whole state for sharing or reviewing as one piece.

One self-contained file per major object (table, view, function) holds everything about that object for sharing a single object.

By convention these live under `state/`, for example `state/database.json`, `state/database.md`, and `state/database/<domain>/<kind>/<name>.md`. Adapt the data format and directory to the host repository; the shape of the idea is what matters.

## The completeness guard

The report counts the object kinds it does not yet capture, by convention under an `other-objects` section (sequences, materialized views, partitioned tables, event triggers, default privileges, and so on). A non-zero count is an object kind the report does not yet describe. This guard is how the tool tells you it is incomplete for a given database, rather than silently omitting something.

When you build the tool, include this guard. When you run it, treat any non-zero count as either work to add or a documented out-of-scope decision.

## Why this exists

In a database-backed application, the real state of the system lives in the database. When the public surface is views and functions and the security is row-level security on private tables, the contract and the boundary are in the catalog, not in the application code. That state is hard to see: the authoritative record is usually a large dump and a history of migrations, and there is rarely a command that returns the current state in a readable form. Answering a concrete question, such as which rows of a table a caller can see, means reading migrations and policy definitions by hand and assembling the answer from several places. Introspection treats "what is the state right now" as a class of problem, not a one-off script.

## What it changes for humans and agents

The state is shareable offline. Because the renderings are committed files, anyone can read, search, diff, and reason about the schema with no running database and no credentials, which lets teams and different intelligences work on the database structure asynchronously. Because headings encode the structure, a reader or tool can parse just the outline of the complete document to get a full map without loading every file.

The state is a time series. Deterministic, migration-stamped output under version control turns the git history into a reviewable record of how the database evolved, where every diff is a real change rather than noise.

For a human, the database stops being a large dump: the complete document opens with a full outline, a click lands on a table, and a single object file is clean to attach to a review. For an agent, the state becomes addressable: a path into the data file returns a fact, a search for the absent-comment marker returns the worklist, and a single object file answers a question without reading migration history.

## Applying the method

Pick a subject with an authoritative live source. Read it read-only. Build one model. Choose one classification path and express it identically in the data keys, the document headings, and the folder layout. Render directly into a committed location, and git-ignore any redundant per-object tree so diffs stay quiet. Keep it deterministic so diffs mean something. Surface the things that should carry descriptions and mark their absence, so the artifact becomes its own worklist.

The reference implementation in `scripts/` is a worked example of all of this for PostgreSQL. Read `references/reference-implementation.md` next when you are ready to build.
