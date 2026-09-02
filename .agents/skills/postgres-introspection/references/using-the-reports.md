# Using the reports with judgment

The generated state answers questions, and `references/reading-the-state.md` shows how to query it. This reference is about what to do with the answers. A report finding is a starting point for judgment, not a verdict. The role of the agent reading the state is diagnosis, not prescription: understand the repository's goals, surface obstacles to them with evidence, weigh trade-offs, and bring decisions to the people who own the database rather than taking them alone.

## The alignment loop

The ideal use of the state is to keep the data layer aligned with what the repository is trying to achieve. Run this loop.

Understand the repository's intent and the goal of its data layer, from its documentation, its database comments, and its code, asking the user where intent is unclear.

Compare the actual data layer, as the state reveals it, against that goal.

For each gap, underperformance, or conflict you find, whether in the decisions, the documentation, or the implementation, surface it to the user with a clear account: what the problem is, what you ground it on, what you researched in the codebase to confirm it, why you judge it a conflict, what options exist when weighed against the global goal, and what you recommend.

Confirm with the user before acting. The loop produces understanding and agreed next steps, not unilateral changes.

## A finding is an obstacle to a goal, not a violation

State each finding against the repository's own goals, not against a generic best practice. A foreign key with no covering index is not a defect by itself; it is an obstacle only if the repository has a goal it blocks, such as a read-latency target on a hot join. The same finding may be irrelevant on a small, rarely joined, or append-only table. Report the finding, the goal it bears on, and the cost of resolving it, and let the owner judge.

When a measure becomes a target, it stops being a good measure. Do not optimize for "every foreign key is indexed" or "every object is commented"; optimize for the repository's stated goals. A report that drives the team to satisfy a metric at the expense of stability, performance, or security has done harm, not good.

## Weigh local context before flagging anything

Before you present a finding, consult the local context, because the people working in the repository know more about its design than this skill can carry.

Read the object's own comment in the state, because a deliberate choice is often recorded there.

Read the repository's documentation and any decision records, because the rationale for an unusual choice often lives in a doc the comment points to.

Look for prior decisions in migrations and pull request history, because what looks like an omission is frequently intentional.

Check whether the repository's own tests or checks already treat the finding as acceptable.

If the finding contradicts a recorded decision, present it as a decision to revisit, with its rationale, not as a bug. If no rationale exists anywhere, that absence is itself worth reporting, and it is a candidate for a new comment per `references/commenting.md`.

## Indexing, security, and performance are trade-offs, not rules

Not everything should be indexed. An index speeds some reads but costs write latency, storage, and operational complexity, and a partial, composite, or expression index may already cover a case a simple check misses. Present the trade-off and the numbers you can estimate, and defer the choice.

Treat security findings with the same care and a higher bar. A table without row-level security may be intentionally public, or it may be a real exposure; the difference is in the intent, which lives in comments and docs, not in the catalog. Never weaken or strengthen a security boundary on your own reading; surface it for review.

Preserve stability, performance, and data security as standing constraints. A change that improves one can harm another, so name the constraint a recommendation would press against, and do not present a change as free when it is not.

## Diagnose and escalate; do not change on your own

Do not alter schema, indexing, or security as a side effect of reading the state. Produce a diagnosis: the finding, the goal it affects, the local context you found, the trade-off, and a recommended next step, which for anything touching schema, security, or indexing is review by the database's owner rather than a unilateral change.

This keeps the introspection capability safe to run often, because reading the state never mutates the database and advising on it never commits a consequential change without a human decision.

## Defer only with the user

Deferral is a decision the user owns, not a way for the agent to avoid one. Do not silently set a finding aside, and do not silently act on it either. Surface it and ask whether to decide now or later. If the user chooses later, record that a decision is pending where the team will see it, such as a tracked note or an issue, so it is not lost. The user may know better than the agent when the right moment to decide is.

## When sources of truth conflict

When the database, the code, and the documentation disagree about intent, treat it as a conflict between the truth and how the truth is recorded, not as something to resolve by yourself. Surface the divergence with evidence from each place. State your grounded view, that intent should live in the database next to the data and structure, and be clear that this is a recommendation, because the user may hold the documentation authoritative for their own reasons. Then ask plainly: the sources disagree, so what is the real intent, and do we align by updating the database or the documentation. Align everywhere in the direction the user chooses, through a migration with consent for any database change, or through the docs.

## Capturing a resolution

When a decision resolves into intent worth keeping, prefer capturing it as a database comment over editing a document, because a comment lives next to the data and travels with the state. Adding a comment is still a change to the database, so ask the user first, explain why a comment next to the data beats a separate document, and apply it through a migration. This keeps the single rule intact: every database change, including a comment, goes through a migration with consent, while introspection only reads.

## Make the repository's goals and constraints explicit when you can

Good judgment needs a reference frame. Recommend, but do not require, that the repository record its architectural goals, its hard and soft constraints, and its notable prior decisions, so findings can be weighed against them. Much of this already exists in documentation and in database comments; help capture it where it is missing, and point findings at it where it is present. The introspection state plus these records together are what let an agent reason about a trade-off instead of guessing at one.
