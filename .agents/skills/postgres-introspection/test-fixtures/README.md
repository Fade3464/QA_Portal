# Test fixtures

These fixtures verify the skill after changes. They are not loaded during ordinary skill use. Load them only when the task is to test that the skill still works.

The example state under `example-state/` is a small, generic, hand-authored sample that demonstrates the output format and the conventions, not real generated output. It uses an ordinary `public` schema with a couple of common tables so the format is clear without exposing any particular application's domain. When you build the real tool in a repository, its output is generated from the live catalogs and will look different.

`verification-prompts.md` holds prompts that exercise the skill's guidance and the reading patterns. Use them to check that a change to the skill still produces correct behavior.

## What the example demonstrates

The example shows the conventions a reader relies on. The classification path is the same in the data keys, the document headings, and the file path. The absent-comment marker `UNCOMMENTED` is distinct from `NONE` for an absent default or empty set. Each object file is self-contained, flat, and greppable, with structure carried by headings rather than decoration. The `accounts.status` comment shows a compact, single-line comment that captures the essence and points to a document for the fuller rationale, while the `users` table and most columns are `UNCOMMENTED` to show the worklist.
