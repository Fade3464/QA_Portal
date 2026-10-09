# V3 person-lookup regression fix

A privacy-sensitive fuzzy matching defect allowed `tl2 Test` to be suggested as `tl1 Test` when only `tl1` was visible to the requester. The person-lookup tool now requires exact matching of any numeric portions of candidate identifiers, retaining spelling suggestions such as `tl1 Tset` for `tl1 Test`. V3 no longer treats approximate or ambiguous matches as confirmed person IDs; instead it requests confirmation before running person-specific analytics. Only direct, unambiguous matches are retained as a conversation referent. All matching remains scoped to completed reports permitted to the authenticated user.

No database migration or GPU change is required. Build Django backend and run `python manage.py test apps.ai_assistant -v 2` against an isolated staging test database before deploying. In production, keep `AI_ENGINE_VERSION=v2` until staging tests pass.
