# Layers: the database and what surrounds it

The database is the core subject, but a real deployment has layers around it, and each layer holds state worth introspecting. The same method applies to every layer: read an authoritative live source read-only, build one model, render it on a classification path, keep it deterministic. This reference describes the layers the reference implementation covers and how to add a layer it does not.

## The core: the database

The database subject is the structure, the security, and the exposed surface: tables, columns, keys, constraints, indexes, triggers, row-level security policies, roles, grants, views and functions with their definitions, and installed extensions. Its output is committed because the schema is the same for everyone who checks out the repository at a given migration version.

This is the subject the reference `database.ts` and its `lib/` modules implement, and the one every introspection setup should build first.

## The committed versus on-demand distinction

A subject's output is committed when it is the same for every checkout at a given migration version, like the schema. A subject's output is git-ignored when it is environment-specific or live, varying by deployment or changing at runtime, like a server's settings or a pooler's live pool health.

Apply this test to every layer you add. Commit what is portable across environments; generate on demand and git-ignore what describes one running environment.

## The cluster

The cluster subject reports the PostgreSQL instance itself: server version, roles, databases, tablespaces, installed extensions, and non-default settings. It answers what kind of server this is and how it is configured.

Its output is environment-specific, because settings and roles vary by deployment and change at runtime, so it is generated on demand and git-ignored rather than committed. The reference is `cluster.ts`. It needs a role allowed to read the relevant catalogs and settings.

## The connection pooler

The pooler subject reports a connection pooler such as PgBouncer: its effective configuration and its live pool health, read through the pooler's admin interface rather than the database wire protocol. It answers how connections are pooled and whether the pools are healthy right now.

Its output is environment-specific and live, so it is generated on demand and git-ignored. The reference is `pgbouncer.ts`, which connects through a pooler admin or stats user. The reference is careful never to carry a field literally named password, even though the admin interface does not expose one.

## The REST layer

The REST layer subject reports a REST interface in front of the database such as PostgREST, over HTTP rather than the wire protocol. It does two things. It downloads the served contract, the OpenAPI document, normalized for determinism and committed, so the contract sits next to the database state. It writes an on-demand, git-ignored report with the service version, admin health, and a reconciliation of the served surface against the exposed schema already captured in the database state. The valuable finding is drift between the served surface and the schema.

The reference is `postgrest.ts` with the HTTP helper `lib/http.ts`. It never reads or emits the JWT secret. Reading a layer must never require or expose a secret.

## Adding your own layers

The four subjects above are examples, not a closed set. Any layer in the deployment that has an authoritative, readable, live source is a candidate: a cache, a search index, a message broker, a storage bucket policy, an authentication provider's configuration, a scheduled-job runner. If a layer holds state that is hard to see and worth version-controlling or auditing, introspect it.

To add a layer, follow the same method. Identify the authoritative live source and a read-only way to reach it. Decide whether its output is committed or on-demand using the test above. Build one model of its state. Choose a classification path and express it identically in the data keys, the document headings, and any per-object files. Keep it deterministic. Surface anything that should carry a description and mark its absence. Never require or expose a secret to read it.

Name each subject's task consistently with the database task, so a contributor discovers the whole family at once, for example a set of tasks that all begin with an `introspect:` prefix. List every subject and what it produces in the repository's agent instructions, per `references/agents-integration.md`, so future agents know which layers are covered and which are not.
