# CallLens AI V3 — person lookup and throttle hotfix

**Scope:** QA Portal Django + AI Insights frontend only. No migration, GPU, or database schema changes.

## Corrected defects

1. `person_tools.py`: removed unsupported `team_leader__username` lookup from the custom email-based portal `User` model. Name and email matching are restricted to the current user's visible completed QA evaluations.
2. `investigation.py`: database/ORM exceptions are logged server-side and converted to a sanitized AIProviderError, which the API presents as HTTP 503 instead of leaking a traceback or returning an unhandled 500.
3. `settings.py`: chat rate changed from hardcoded `15/hour` to configurable `AI_CHAT_THROTTLE_RATE` (default `60/hour`), with per-user protection retained.
4. `AIInsightsPage.tsx`: HTTP 429 displays an estimated wait when the API supplies one.
5. `tests.py`: added real ORM queries for team-leader name/email, authorized-project isolation, agent resolution, and failure-path tests for invalid DB query handling and HTTP 503 responses.

## Controlled deploy on STAGING first

Place this code in the existing repo before building. The Django test environment must have PostgreSQL configured. Keep `.env` at `AI_ENGINE_VERSION=v2` (or `v1`) while testing V3.

```bash
cd /opt/calllens/QA_Portal
docker compose config --quiet
docker compose build backend frontend
docker compose run --rm -e DB_DIRECT=true backend python manage.py check
docker compose run --rm -e DB_DIRECT=true backend python manage.py makemigrations --check --dry-run
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py test apps.ai_assistant -v 2
```

Do not proceed on any failed test. In particular, the new test `test_person_lookup_uses_actual_portal_user_fields` must query real Django/PostgreSQL models successfully. The test creates/destroys only its separate Django test database; do not direct it at the live DB.

Then deploy (after normal DB backup and staging acceptance):

```bash
docker compose up -d --no-deps --force-recreate backend frontend
docker compose exec -T backend python manage.py check
docker compose ps
```

For staging only, after setting up a private encrypted connection to the GPU:

```bash
# Ensure .env has exactly one AI_ENGINE_VERSION and AI_ENABLED assignment.
sed -i 's/^AI_ENGINE_VERSION=.*/AI_ENGINE_VERSION=v3/' .env
sed -i 's/^AI_ENABLED=.*/AI_ENABLED=true/' .env
docker compose up -d --no-deps --force-recreate backend
```

Test the exact failing user message (e.g. `How many reports has Ahsan Tanveer not reviewed?`) using a role-authorized account, then test date resolution, repeat-criterion questions, permission isolation, the prototype banner, and rate limit messaging. Confirm no `FieldError` or HTTP 500 appears in logs.

**Rollback:** set `AI_ENGINE_VERSION=v2` and recreate backend. No schema rollback required.

**Validation limitation:** static syntax/contract checks can run in the artifact environment. Full Django tests and real Qwen tool calls must run on the deployed staging containers.
