---
name: postgres-introspection
description: Teaches an AI agent to build a database introspection capability inside the repository it is working in. Introspection is a read-only tool that reads a live database's catalogs and renders the current structure, security (row-level security, roles, grants), views, functions, and extensions into committed, navigable files shareable without a running database or credentials. Use when a repository needs an always-current, addressable picture of its database state, when asked to introspect a database, generate or refresh database state, make a schema readable for humans and agents, audit which callers can reach which objects, or capture the architect's intent behind the schema. The method is database-agnostic with a PostgreSQL reference implementation, and extends to layers around the database such as the cluster, a connection pooler (PgBouncer), and a REST layer (PostgREST). Not for authoring migrations, asserting expectations (that is validation), or writing hand-maintained documentation.
---

# Database introspection

## Goal

This skill teaches an agent to give a repository a shareable, always-current, intent-carrying picture of its own database, and to keep that capability after the skill is gone.

It addresses two problems at once. The first is a tooling gap: there is rarely an easy, read-only way to see the current state of a database, so the truth lives in a large dump and a history of migrations that nobody can read quickly. The second is an intent gap: the architect's reasons behind the schema, the why behind a default, a status value, a definer function, or a coupling, are not in the database at all. The tool solves the first. The commenting discipline solves the second. Neither alone is enough.

The goal stack, from broad to specific:

- Global goal: the repository holds a picture of its database that another mind can read without the database running, that stays current, and that carries the architect's intent alongside the structure.
- Communication goal: transfer that picture across humans, AI agents, and tools, including across teams and across different intelligences, without a live database or credentials.
- Task goal: build the read-only introspection tool in this repository, capture hidden intent in comments, wire generation to the migration run, and read the reports with judgment.

Two properties follow from committing the output. The files are shareable offline: anyone can read, search, diff, and reason about the schema with no database and no credentials, and because headings encode the structure, a reader or tool can parse just the outline to get a full map cheaply. The files are a time series: deterministic, migration-stamped state under version control turns the git history into a reviewable record of how the database evolved.

## Terms

Define these before using them, because they carry different meanings in different contexts.

- Introspection: reading a live source read-only and rendering its current state into files. It is generated, never hand-authored.
- State: the rendered snapshot of the database's current structure, security, and exposed surface, as of a migration version.
- Subject: one thing introspected. The database is the core subject; the cluster, a pooler, and a REST layer are additional subjects.
- Cluster: the PostgreSQL server instance itself (its roles, databases, settings), not a Kubernetes or sharding cluster.
- Catalog: the database's own system tables that describe its structure, the authoritative live source the tool reads.
- The navigable data file and the complete document: the two committed renderings, a single queryable data file and a single whole-schema document.

## What introspection is, and what it is not

Introspection describes live reality and is generated from it. Validation asserts that live reality matches an expectation and answers yes or no. Documentation records intent and is authored by a person. This skill builds introspection only. The full method, invariants, and classification path are in `references/approach.md`, which you must read before designing anything.

## When to use

Use this skill when a repository has a database whose real state is hard to see from the application code, and someone wants that state captured in readable, navigable, version-controlled files. Triggers include introspecting a database, generating or refreshing database state, making a schema readable for humans and agents, auditing which roles or callers can reach which objects, and capturing the intent behind the schema.

Use it for PostgreSQL through the reference implementation, and for other relational databases by porting the method per `references/other-databases.md`.

## When not to use

Do not use it to author or modify migrations, to assert that the database matches an expectation (that is validation), to write hand-maintained documentation of intent, or to model a database for an ORM.

## Before you build: confirm intent

Do not start building on contact. Confirm intent first, and do this every time until the user has confirmed in the current session.

Tell the user the skill builds an introspection tool inside this repository and commits generated state files, then ask whether they want to proceed with creating the tooling here. Offer to walk them through `references/approach.md` first. Proceed only after the user confirms. If they only want to understand the method, stay in explanation mode and create no files.

While confirming, check that the user has a safe place to run this and the means to protect their data: a dev, test, or CI database to point at, or backups and the ability to recreate the database. A less technical user may not know the data-layer impact, so make it explicit before proceeding.

## Data safety

Introspection reads; it must never put data at risk. Hold these rules above any local convenience.

The tool opens a read-only transaction and never writes to the database it inspects.

Never reset, recreate, drop, clean, or run migrations against a data-bearing or production database to obtain a state to introspect. Obtaining a migrated database is about which database you point at, not about destroying one.

Never point the setup, or the migration-wired generation, at a production database without the user's explicit, informed consent and a clear explanation of what will run and its impact.

Preserve existing data always, including on local and test databases. Stop and ask if your own actions, or a script you generate, could alter or destroy data, or could affect the operability of the database.

## Adapt to your own capabilities and to the repository

This skill is agnostic of which agent runs it. Do not assume a capability you have not confirmed, including the ability to execute scripts or run shell commands. If your environment can run commands, run them and report the output; if it cannot, write the files, give the user the exact commands, and continue from their results. State which mode you are in.

Respect the repository. The reference implementation is PostgreSQL plus TypeScript, but that is an example, not a mandate. Fit the capability into the repository's existing language, runtime, task runner, layout, naming, and version-control rules. The method transfers; the implementation matches the host.

## Required inputs and assumptions

You need read access to a fully migrated database, one whose schema reflects all migrations with no ad-hoc drift, reached through a connection string the repository already uses or that the user provides. Introspect such a database rather than a working database carrying manual changes, so the output reflects the migrations and not local drift. A fully migrated database is one you point at, not one you create by resetting another; see Data safety above.

You need to know the repository's stack, conventions, and database layout, which you discover by inspecting the repository and asking the user when intent is unclear. Do not assume a schema layout; the example schema names in this skill are illustrative.

You need a place to write committed state files, by convention a `state/` directory at the repository root unless the repository has a different convention. For optional layers you need the relevant access, described in `references/layers.md`.

## Core workflow

Each step names its purpose so you can adapt it to the repository rather than follow it blindly. Read the referenced file before performing the step.

1. Confirm intent, so you never build something the user did not want. See the gate above.
2. Read `references/approach.md`, so the invariants that make the output trustworthy are in mind before you design.
3. Assess the target repository, so the tool fits the host: its stack, task runner, where generated artifacts live, version-control conventions, the database and how the app connects, the migration tool, and any layers in front of the database.
4. Decide the fit, so the design matches local reality: implementation language, what is committed versus git-ignored, and the classification path built from the database's real structure. See `references/reference-implementation.md`.
5. Recreate the tooling in the repository, so the capability outlives this skill: a read-only connection, the catalog queries, one object-centric model, and a renderer that writes committed files. Keep the rendered Markdown minimal and greppable per the rendering discipline in `references/approach.md`.
6. Generate and verify, so the state is trustworthy: run against an already-migrated dev, test, or CI database, confirm a second run produces no diff, and confirm the completeness guard reports no uncaptured object kinds. If no migrated database is available, ask the user; never create one by a destructive operation.
7. Cover additional layers when present, and add your own, per `references/layers.md`.
8. Capture intent in comments, so the state carries the why and not only the what. Read `references/commenting.md`.
9. Wire generation to the migration run and make the capability discoverable, so the state stays current and future agents find it. Read `references/agents-integration.md`.

When you use the reports to advise on the database, do not apply rules mechanically. Read `references/using-the-reports.md` first: weigh findings against local documentation and prior decisions, frame them as obstacles to the repository's goals, and defer changes to schema, security, and indexing rather than prescribing them.

## Expected outputs

A runnable introspection tool living in the repository, fitted to its stack, that anyone can run later without this skill.

Committed state files: at minimum a single navigable data file and a single complete document, plus a generated per-object tree that is typically git-ignored because it duplicates the other two.

Version-control entries that commit the durable artifacts and ignore the environment-specific and redundant ones, and an updated agent instructions file that tells future agents the capability exists and how to read the state.

## Self-removal after completion

Decide this only after the tooling is installed, verified, and discoverable.

If the skill's own files live inside the target repository, ask the user whether to remove the skill now that the capability lives in the repository on its own. Remove it only if they agree.

If the skill is installed outside the target repository, for example in a global or shared location, do not suggest removing it; it serves other repositories.

If you cannot tell where the skill lives, ask the user before suggesting removal.

## Reference loading guidance

Load `references/approach.md` first, always; it is the method and the vocabulary.

Load `references/reference-implementation.md` when you design or write the tool.

Load `references/reading-the-state.md` when you consume the state or teach others to.

Load `references/using-the-reports.md` when you turn findings into advice about the database.

Load `references/commenting.md` when you capture intent in comments.

Load `references/layers.md` for a pooler, a REST layer, a cluster, or a layer not covered here.

Load `references/other-databases.md` when the target database is not PostgreSQL.

Load `references/agents-integration.md` when you wire generation to migrations and discoverability into the repository's agent instructions.

## Completion criteria

The tool reads the database read-only and never writes to it. A second run against an unchanged database produces no diff. The completeness guard reports no uncaptured object kinds, or they are documented as out of scope. The durable state files are committed and the redundant or environment-specific outputs are git-ignored. Generation is wired to the migration run, and the repository's agent instructions describe the capability and how to read the state. No existing data was altered and no destructive operation was run without the user's informed consent. The user has confirmed they wanted the tooling created here, and the self-removal decision has been handled.
