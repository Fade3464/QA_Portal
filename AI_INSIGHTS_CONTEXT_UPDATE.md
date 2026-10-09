# CallLens QA Portal — AI Insights contextual accuracy update

This is a targeted update to the **user-supplied V3 repository**. No new Django migration, GPU image, call ingestion workflow, scoring policy, or non-AI interface changes are introduced.

## Changes

- AI replies render a **restricted, escaped subset of Markdown** (bold `**...**`, emphasis, inline code, headings, numbered and bulleted lists). Model-provided HTML, links, and images are never interpreted.
- Known QA-domain spelling mistakes are normalized without editing named people, companies, projects, or dialers. Fuzzy person and dialer matching searches **only records already authorized for the user**; multiple candidates are disclosed rather than guessed.
- V3 knows the application's current **QA scorecard headings, subheadings, scoring maxima, Not Reached semantics and critical-error taxonomy**. For a specific historical evaluation, a new read-only tool returns headings/criteria from its **saved scorecard snapshot**, with status, scores, applicability, critical errors and review ID.
- Two optional tools expose carefully bounded samples of *reviewer-written* improvement advice and coaching suggestions, never recorded audio, raw lead data, transcripts, arbitrary review notes or customer URLs. These are **human QA observations**, not independently proven causes.
- New tools distinguish authorized **Call Library volumes** (by `received_at`) from completed **QA evaluation volumes** (by `completed_at`). A dialer name is resolved to an authorized dialer ID; the engine must not substitute a project name or claim a project-level count proves a dialer count.
- A question about one unspecified “our project” uses that single visible project, or asks which project when multiple visible projects exist. It does not expand singular requests to the whole branch.
- “Which agent has the most violations?” uses the **per-agent critical-error-review ranking**, not a frequency of error types. Worst-average-score rankings still have the existing minimum of three scored evaluations.
- Greetings can get a simple acknowledgment instead of a failed analytic plan. Standalone topics start a new default period; explicit conversational follow-ups may retain an earlier period. Model-produced dates cannot override Django calendar resolution.
- The fallback answer is now metric-specific when numerical claims cannot be corroborated.

## Protection of free-form QA feedback

`AI_SEND_REVIEW_FEEDBACK=false` **by default**. Headings, criterion scores, applicability and critical error IDs remain available without this flag. With the flag disabled, no reviewer-written free text is sent to the model by the new context tools.

After securing the CallLens-to-GPU connection with HTTPS or a private encrypted tunnel, operators may explicitly opt in to send **short, heuristically redacted excerpts** of `feedback_summary`, `strengths`, `improvement_areas`, `expected_behavior` and `coaching_plan`:

```dotenv
AI_SEND_REVIEW_FEEDBACK=true
```

This is not guaranteed anonymization: human reviewers can include identifiable details in prose. Conduct a privacy review first. Existing tool protections, Django role/scope rules and the prototype banner remain unchanged.

## Deployment and testing

Integrate these changed files into the existing repository and push to `master` before pulling on WA-node. **Keep V2 enabled in production while validating V3 on staging.**

```bash
cd /opt/calllens/QA_Portal
git pull --ff-only origin master
cp -p .env ".env.backup.$(date +%Y%m%d-%H%M%S)"
docker compose build backend frontend
docker compose run --rm -e DB_DIRECT=true backend python manage.py check
docker compose run --rm -e DB_DIRECT=true backend python manage.py makemigrations --check --dry-run
docker compose run --rm -e DB_DIRECT=true -e PRODUCTION=false -e DJANGO_DEBUG=false -e SECURE_SSL_REDIRECT=false -e AI_ENGINE_VERSION=v3 backend python manage.py test apps.ai_assistant -v 2
# Only after tests pass and normal change controls:
docker compose up -d --no-deps --force-recreate backend frontend
docker compose ps
```

For staging V3 activation set `AI_ENGINE_VERSION=v3` and `AI_ENABLED=true` in the QA Portal `.env` and recreate backend; leave the GPU service untouched. Rollback: set `AI_ENGINE_VERSION=v2` and recreate backend. No schema migration to reverse.

**Validation disclaimer:** The packaged source was Python-compiled, AST-checked, and TypeScript/TSX syntax-parsed offline. Django/PostgreSQL integration tests, frontend Vite build and real GPU tool-choice evaluation must be run in the deployed environment. Staging tests must cover API access across teams, projects, branches, and repeated conversations. The model remains experimental and should not make unattended staffing or compliance decisions.
