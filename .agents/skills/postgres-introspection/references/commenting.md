# Commenting the database to capture hidden intent

Introspection surfaces object comments wherever an object can carry one. That is only valuable if the comments carry something worth surfacing. Capturing the architect's hidden decision logic is half the value of the whole method, so treat this as a pillar, not a polish step. This reference explains what belongs in a comment, the two surfaces a comment can live on, and how the absent-comment marker becomes a worklist.

## Why comments are where intent belongs

The database object already shows its own shape. A column shows its type, nullability, and default. A foreign key shows what it references and its delete rule. A policy shows its expression. What the object cannot show is why it is the way it is: the decision, the constraint that forced it, the meaning of a status value, the caller a definer function trusts, the coupling that is not visible from the object alone.

That hidden decision logic usually lives only in the architect's head, a pull request discussion, or a migration nobody rereads. When it is lost, the next agent or engineer reconstructs intent by guessing from names and shapes, and the guess is often wrong. Proximity is fidelity: the closer the context sits to the thing it explains, the more likely it is to be read and trusted. A database comment is the most proximate place intent can live, and it travels with the object into the generated state.

## Comment on the why, not the what

A comment carries hidden intent, not a restatement of what the object already shows. Do not restate the type, the nullability, or the obvious purpose of a column named `created_at`. State the thing that is not visible: the reason for a non-obvious default or nullability, the meaning of a status value, the trust boundary or caller of a definer function, a hidden coupling between objects, or a constraint that the shape alone does not reveal. A comment that restates the schema is worse than no comment, because it adds noise without adding intent.

## Two surfaces: the code layer and the database comment

Intent is recorded on two surfaces, and they have different rules.

The code layer is comments in the migration that makes the change, in decision documents, and in scripts. This layer can be rich and structured. Use the repository's code-comment conventions, and record the full rationale here: why the decision was made, the constraints that shaped it, side effects, and provenance such as a date or version and a ticket or decision reference. Structured tags such as a why, a constraints, a since, and a see reference make each piece individually findable.

The database comment is the `COMMENT ON` text itself. It must stay compact, because it renders in many places: the database via a client, the terminal, the generated state files, and an agent's context. Keep it to a single line of one to three short sentences, with no line breaks and no special characters, so it displays cleanly everywhere. Capture only what matters most: the essence of the hidden intent.

## When the intent does not fit one line

A comment that captures the rationale in a compact line is complete. It needs no document reference, and adding one would scatter a truth that already lives in one place. A reference is only for genuine overflow.

When the rationale is longer than a compact comment can hold, do not stretch the database comment. Put the full rationale in the code layer, in a decision document or an expanded code comment, and make the database comment state the essence and point to that document with a short path relative to the repository root.

```sql
comment on column billing_accounts.status is
  'Lifecycle: active, then suspended, then closed. Only active accounts may create users. See docs/billing/account-lifecycle.md.';

comment on function core.has_project_action is
  'Definer helper trusted by project policies to check the caller has an action on a project. See docs/security/project-access.md.';
```

The reference is plain text and relative to the repository root, so it survives in the terminal and the files and a reader can follow it without the database.

## The database is where intent should live

The application derives its data from the database, and intent should derive the same way: captured next to the data and the structure it explains, where one definitive tool can export it. That makes the database comment the place the truth should live, and documentation a derivation from it.

This is a recommendation the agent carries, not a ruling it imposes. When the database, the code, and the documentation disagree about intent, that is a conflict between the truth and how others record it, and the agent does not decide the winner on its own. It surfaces the conflict and asks the user where the real intent is and in which direction to align everything, then aligns accordingly. The procedure for that conversation is in `references/using-the-reports.md`.

## Record the comment in the migration that makes the decision

A comment is part of the change it explains, so write it in the same migration that creates or alters the object, with a `COMMENT ON` statement, and put any fuller rationale in that migration's code comments or the referenced document at the same time. This attaches the intent to the decision at the moment it is made, rather than added later from memory. Because the project operates on the database through migrations, the migration is the natural and durable home for both surfaces.

## Keep comments true, or remove them

A comment that contradicts the object is worse than none, because every reader that trusts it is misled. When a migration changes an object, update its comment in the same migration, or remove a comment that no longer holds. Stale intent is a liability, not a record.

## How introspection turns missing comments into a worklist

The tool surfaces every comment in the state and marks every object that has none with a distinct marker, by convention `UNCOMMENTED`, different from the `NONE` used for an absent default or an empty set. The distinction matters: `NONE` is a fact about the object, while `UNCOMMENTED` is a task about the documentation.

This turns the generated state into its own worklist. A search for the marker returns exactly the objects whose hidden intent has not been captured yet.

```bash
grep -rln 'UNCOMMENTED' state/database/
```

```bash
jq -r '
to_entries[]
| select(.value | type == "object" and has("tables"))
| .key as $schema
| .value.tables | to_entries[]
| select(.value.comment == null)
| "\($schema).\(.key)"
' state/database.json
```

Work the list down over time. Every comment added is intent that the next reader gets directly from the state instead of reconstructing.

## Why this compounds with introspection

Introspection makes the database state addressable, and comments make the state meaningful. Together they let any reader answer a question from the committed files: open one object file and read both its shape and the reason behind its shape, without a running database, without credentials, and without reading migration history. The commenting practice is what raises the answer from correct-about-structure to correct-about-intent.

When you build introspection, build the absent-comment marker into the renderer, and tell the repository's contributors and agents, through the agent instructions in `references/agents-integration.md`, that the marker is a worklist and that new decisions are commented in the migration that makes them.
