# V3 critical-violation identity deduplication fix

The earlier V3 regression `test_specific_recorded_critical_violation_has_review_evidence` failed because the same dialer agent's two reviews were incorrectly treated as multiple agent identities.

## Root cause

`Review.Meta.ordering` uses `-assigned_at`. In Django/PostgreSQL, `values(...).distinct()` without clearing ordering can include order-by columns in the DISTINCT selection; different assigned dates then make rows for the **same agent** look different. In addition, display names may change across a dialer login.

## Changed files

- `backend/apps/analytics/services/recurrence.py`: clears implicit ordering before finding distinct `(call__dialer_id, call__agent_user)` candidates, case-folds usernames for identity, and re-fetches all matching *authorized* evaluations for the unique dialer/login. Never treats a missing login as a stable identity. Keeps explicit disambiguation when truly distinct logins or dialers match.
- `backend/apps/ai_assistant/tests.py`: adds 5 PostgreSQL/Django regression tests for two reviews by the same agent, historical renamed display names, matching names across different logins, same login across dialers, and isolation from unauthorized project records.

No migration, frontend edit, new external dependencies or GPU changes.

## Safe validation (staging)

```bash
cd /opt/calllens/QA_Portal
docker compose build backend
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py test apps.ai_assistant -v 2
```

Stop if any test fails. If all pass, recreate backend via `docker compose up -d --no-deps --force-recreate backend` and test the exact question against synthetic QA records. Retain the current engine setting if V3 has not passed its staged acceptance tests. 

## Validation status

Python source compilation and package integrity are checked offline. Full Django/PostgreSQL integration tests and live Qwen calls **must be run on staging**; they could not be run in the artifact environment.
