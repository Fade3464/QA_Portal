# V3 request-contract hotfix: named team-leader backlog

## Problem reproduced

The original 123-test Django suite reported one error:
`test_model_driven_leader_lookup_then_backlog` had no `context_state.last_person`.
The cause was not missing state serialization: the planner interpreted
"How many reports has tl1 Test not reviewed?" as an unnamed/collective
leader backlog. The context code correctly clears `last_person` for a
collective question; preserving it unconditionally would have introduced
stale-person and authorization risks.

## Changes

- `backend/apps/ai_assistant/query_contract.py`: treat "has/have <person>
  not reviewed" as a named leader backlog, not a collective backlog.
  Protect against matching auxiliaries, pronouns and broad quantifiers as
  people. Also recognize "not yet reviewed" and "not been reviewed" as
  pending-review questions.
- `backend/apps/ai_assistant/tests_contracts.py`: add two pure contract
  regressions for named and collective wording.
- `backend/apps/ai_assistant/tests.py`: strengthen the failing Django test
  to give the PM visibility of TWO different team leaders. It now checks
  the target team-leader filter, stored named query specification, and
  authorized review evidence, not only whether a `last_person` key exists.

No database migration, GPU change or dependency change is required.
Existing `AI_ENGINE_VERSION=v3` and V1/V2 rollback paths are unchanged.

## Validation in artifact environment

- 16 request-contract unit tests: passed (including the 2 new tests).
- Python syntax/bytecode compilation: passed.
- Both ZIP archives: integrity and expected changed-file verification passed.
- The Django/PostgreSQL suite and real Qwen requests: not executed here.

## Required staging validation

After applying these source changes to your Git repository and pulling to
staging, run:

```bash
cd /opt/calllens/QA_Portal
bash scripts/validate_ai.sh
```

The validation script builds backend/frontend and runs the full Django AI
suite against its isolated PostgreSQL test database; it does NOT recreate
running containers. Expect the original failing test to pass. Do not deploy
if ANY test is failing. Follow with the synthetic live-provider acceptance
and role-scope tests in `AI_REQUEST_CONTRACT_UPDATE.md` before production.
