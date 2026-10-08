# QA Portal — AI Insights UI integration

## Delivered

This increment extends the existing **Django AI backend** with a frontend UI, preserving the portal's Ant Design, React Router, session authentication, CSRF handling, and theme tokens.

- **Team leaders:** AI Insights link in the sidebar and a shortcut from the team command center. Questions use the existing server-authorized team scope.
- **Project managers and supervisors:** AI Insights link in the sidebar and a shortcut from project performance. Questions use their permitted company / branch / project scopes.
- **System administrators (superusers):** AI Insights appears in the sidebar for permitted system administrators. Ordinary QA analysts and unauthorized users do not receive the menu entry or route access.
- **AI workspace:** responsive chat, four role-specific starter questions, conversation history and deletion with confirmation, read-only/evidence notices, loading/empty/error states, rate-limit and provider-outage messaging, enter-to-send and shift+enter support.
- **Evidence navigation:** QA report citations from controlled AI tools link to `/queue?review=<uuid>`, which opens the existing report details using the **same scoped** `/api/v1/calls/reports/<uuid>/` endpoint as the report table. It does not bypass Django access checks.
- **Saved evidence:** AI messages persist minimal `evidence` and `tools_used` JSON metadata, so report links survive refreshing or reopening a conversation. Migration `ai_assistant.0002_message_evidence` adds these fields. Raw tool outputs are not stored.
- **Security:** browser connects to Django session-authenticated `/api/v1/ai/` only. No GPU endpoint or API keys in frontend. AI output is rendered as plain text, not untrusted HTML. Actions like scheduled email and admin skills are deliberately not exposed because their backend is not implemented.

## Files changed in this increment

- `frontend/src/App.tsx`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/pages/AIInsightsPage.tsx` (new)
- `frontend/src/lib/ai.ts` (new)
- `frontend/src/pages/DashboardPage.tsx`
- `frontend/src/pages/ProjectPerformancePage.tsx`
- `frontend/src/pages/ReportsPage.tsx`
- `frontend/src/styles.css`
- `backend/apps/ai_assistant/models.py`
- `backend/apps/ai_assistant/views.py`
- `backend/apps/ai_assistant/tests.py`
- `backend/apps/ai_assistant/migrations/0002_message_evidence.py` (new)

## Deployment (staging first)

1. Merge this patch **on top of** the previous AI backend version or deploy the provided full updated repository. Do **not** apply the frontend patch to a checkout missing `apps.ai_assistant`.
2. Set appropriate backend `AI_ENABLED`, `AI_LLM_BASE_URL`, `AI_LLM_MODEL` and authenticated inference configuration as described in `AI_BACKEND_IMPLEMENTATION.md`. Keep the inference service private; the browser never uses it directly.
3. Run in staging, using your Compose service names:

```bash
# Check the backend and migrations
# Use the same Compose/env-file parameters as your deployment.
docker compose run --rm backend python manage.py check
docker compose run --rm backend python manage.py makemigrations --check --dry-run
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py test apps.ai_assistant -v 2

# Rebuild and recreate after review
docker compose build backend frontend
docker compose up -d backend frontend
```

If your backend image runs migrations automatically, follow the existing deployment sequence; avoid doing two concurrent migrations.

4. Validate these scenarios as real portal users:
   - QA analyst: no AI menu; navigating to `/ai` redirects home; direct AI API access returns HTTP 403.
   - Team leader: ask for pending reports and repeat mistakes; verify other teams do not appear.
   - Project manager: ask project analytics; verify unassigned projects cannot be inspected.
   - Supervisor: confirm branch-only results; confirm another branch's UUID cannot open via evidence URL.
   - Admin superuser: ask a company/branch-specific question; verify correct filtering.
   - Send questions; refresh; reopen conversation; confirm evidence links persist and open the correct report.
   - Remove a project assignment while logged in; confirm older conversation access is denied when scope changes.
   - With `AI_ENABLED=false` or provider unavailable, verify explicit unavailable states rather than broken chat.
   - Narrow window/mobile layout: history drawer, composer, focus states, contrast in light/dark mode.

## Known boundaries

- The UI is **not a replacement for backend access checks**. All access control remains enforced by Django.
- Existing AI APIs are synchronous. Long inference calls may require future background jobs / streaming for smoother UX; this version includes loading feedback but not streaming or cancellation of server-side inference.
- Admin-configurable skills, email/Gmail actions, scheduling and routines are a separate module and have **not** been implemented in this increment.
- Staging integration tests, real-browser UI tests, frontend production build, and end-to-end tests against your deployed GPU require the actual deployment environment. A static compile/parse check alone is not production validation.
