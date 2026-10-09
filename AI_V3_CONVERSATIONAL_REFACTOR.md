# CallLens V3 — conversational investigation and ranking correction

**Status:** implementation candidate. A real PostgreSQL-backed Django test run and live Qwen multi-turn testing are required before production activation. No database schema change or GPU change is included.

## Changed source (focused patch)

- `backend/apps/ai_assistant/conversation_analysis.py` (new): query-only structured ranking state, deterministic ties, rank positions, full top-N listing and next-distinct-rank references. No raw report data persisted.
- `backend/apps/ai_assistant/timeframes.py`: rolling 2-week / N-week and fortnight windows, respecting Django's active branch timezone; dates are applied server-side to each tool.
- `backend/apps/ai_assistant/investigation.py`: typed model tool-selection intent, optional metric, a bounded recovery query if the model fails to execute essential approved analytics, deterministic answer rendering for rankings, recurrence, review workflows and named-agent violations. Ranking follow-ups requery the current authorization and actual QA data; the model does not invent numbers or use a prior response as data.
- `backend/apps/analytics/services/recurrence.py`: exact agent critical-error details, categories and bounded review evidence from the existing authorized review queryset. Same display names across dialers are not silently conflated.
- `backend/apps/ai_assistant/tools.py`: read-only registry declaration for the above tool.
- `backend/apps/ai_assistant/tests.py`: integration/conversation tests with mocked model selection but real Django ORM and authorized synthetic QA fixtures, plus deterministic calendar and ranking contract tests.

## Semantics and limitations

1. "Past 2 weeks" as of 2026-10-09 means the rolling inclusive 2026-09-26 to 2026-10-09. "Last week" (without a number) still means the previous complete Monday–Sunday calendar week.
2. Agent rankings require an explicit definition. "Most problems" defaults to the number of submitted QA evaluations **with at least one recorded critical error** unless an unambiguous score-based metric is chosen; the result explains this proxy. Other defects (submaximum criterion scores) are tracked independently as repeated QA mistakes.
3. Ties share competition rank: four agents at the highest count all rank 1; the next group is rank 5. "Third worst" is interpreted as the **third distinct metric value group**, with its actual competition rank explicitly identified. This does not assign fictional rank 3 to someone tied for first.
4. Top-N output uses up to 25 independently authorized result rows, not only the first; a user can ask for another person, next rank, other nine, or a revised period. Changing subject to team leaders or changing ranking metric resets the prior agent ranking path.
5. Conversation state stores the authorized *query specification* (metric, order, date window and narrowing scope filters), not prior reports or a model-generated leaderboard. Every follow-up calls `rank_agents` again under current permissions.
6. Exact agent-critical-violation inspection uses a dialer-qualified identity and returns only explicitly saved critical error categories and review UUIDs. Ambiguous identities ask for a specific dialer; feedback notes/customer details are not fetched.
7. The fallback helps recover when Qwen declines to use an essential read-only analytics tool. It never guesses a UUID or changes identity authorization, and it only supports a finite set of unambiguous business queries. Unknown, nuanced or unsupported questions may still require clarification.
8. All review scope restrictions, existing UI prototype warnings, customer-data redactions and V1/V2 rollback remain unchanged. Reviewer free-text is still opt-in through `AI_SEND_REVIEW_FEEDBACK` and must not be enabled over plaintext GPU transport.

## Local validation performed

- Python source compilation and AST parsing across the backend apps.
- 24 isolated contract checks of calendar rules, ties, follow-ups, first/second/third/top-N answers, role topic changes, and safe recovery query planning.
- Source ZIP integrity and changed-file comparison.

**Not performed locally:** PostgreSQL-backed Django integration tests, real Qwen API model output tests, end-to-end browser test and high-load/timeout profile. Python/Django dependencies were unavailable from this workspace's package source. Do not interpret isolated contract checks as end-to-end proof.

## Staging validation and safe deployment

Back up the database before deployment. `AI_ENGINE_VERSION=v1` or `v2` can remain active while V3 code is installed. Use private encrypted transport before sending real QA records to the GPU.

```bash
cd /opt/calllens/QA_Portal
git pull --ff-only origin master
docker compose build backend
# Temporary test settings are confined to the run container.
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py check
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py makemigrations --check --dry-run
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py test apps.ai_assistant -v 2
# ONLY if tests pass and after staging acceptance, recreate backend while the chosen engine flag is set in .env:
docker compose up -d --no-deps --force-recreate backend
docker compose exec -T backend python manage.py check
docker compose ps
```

The integration suite uses mocked model responses. **Separately** run the following multi-turn conversations against live Qwen with synthetic known QA records, collecting tool selection, truthfulness, scope checks, latency and failure rate:

- "What agents had the most problems in the past 2 weeks?" → period 2026-09-26 to 2026-10-09, metric disclosed.
- "Who's next after Zaran?" → reuse metric, requery authorized data, handle a tied first group.
- "Who is the 2nd worst?" / "and third worst?" → rank semantics explicit.
- "Give the top 10 worst agents" / "what about the other nine?" → complete list of authorized eligible entries, not only first.
- "Who's worst in the past 5 days?" → new explicit date window wins.
- "What critical violation was recorded for Zaran?" → exact agent identity and supporting authorized review UUIDs.
- "Who is the worst team leader at reviewing?" → leader backlog, not agent scoring.
- "Who repeatedly made the same QA mistake?" / "same critical violation?" → proper separate recurrence tools.
- Subject change to another branch/project and permission revocation mid-conversation must never expose stale scoped results.

For rollback, set `AI_ENGINE_VERSION=v2` (or `v1`) in `.env`, then recreate only `backend`. No V3 migration reversal needed.

### Ranking identity correction

Agent ranking groups evaluations by **(dialer ID, dialer agent username)**, not editable agent display name. The displayed name is representative metadata; changing it cannot create a second ranking entry for the same login within a dialer. Two separate dialers that both use username `8005` remain separate agents.
