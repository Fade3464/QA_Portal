"""Model-facing typed tool declarations. All calculations live in apps.analytics.services."""
from .registry import register, S, I, E, DATES, FILTERS
from apps.analytics.services import discovery, performance, reviews, recurrence, context
from .person_tools import lookup_visible_people

register('get_scorecard_policy', 'Return the currently configured QA criteria, scoring benchmark and critical-error definitions. This is code-defined policy, not RAG.')(discovery.get_scorecard_policy)
register('list_available_branches', 'Resolve company and branch UUIDs from names appearing in reports accessible to the signed-in user.', DATES)(discovery.list_available_branches)
register('list_available_teams', 'List team IDs and names represented in reports visible to the signed-in user.', {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36)})(discovery.list_available_teams)
register('list_available_projects', 'List project names with reports visible to the current user.', {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36)})(discovery.list_available_projects)
register('find_agents', 'Resolve dialer agent usernames and display names within visible reviewed calls; names may be ambiguous.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'search': S('Part of agent display name or dialer username', 80), 'limit': I('Maximum results', 1, 30)}, ('search',))(discovery.find_agents)
register('get_qa_overview', 'Aggregated QA scores, volume, critical errors and partial calls for an authorized date/scope.', FILTERS)(performance.get_qa_overview)
register('get_agent_performance', 'QA summary for one dialer agent username (optionally within a team or project).',
          FILTERS, ('agent_user',))(performance.get_agent_performance)
register('get_team_performance', 'QA summary of a team identified by team UUID.',
          FILTERS, ('team_id',))(performance.get_team_performance)
register('get_project_performance', 'QA summary for a project name visible to the current user.',
          FILTERS, ('project_name',))(performance.get_project_performance)
register('rank_agents', 'Rank dialer agents by average QA score, review volume or number of critical error reviews; minimum 3 scored reviews for score ranking.',
          {**FILTERS, 'metric': E('Ranking metric', ('average_score', 'critical_error_reviews', 'evaluation_count')),
           'limit': I('Maximum agents', 1, 25),
           'order': E('best = highest score/fewest errors; worst = lowest score/most errors', ('best', 'worst'))}, ('metric',))(performance.rank_agents)
register('rank_teams', 'Rank accessible teams by average scored QA percentage or number of completed reviews.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'project_name': S('Exact project name'),
           'metric': E('Ranking metric', ('average_score', 'evaluation_count')),
           'limit': I('Maximum teams', 1, 25),
           'order': E('best or worst', ('best', 'worst'))}, ('metric',))(performance.rank_teams)
register('get_score_trend', 'Daily average QA score and completed-review volume, filtered to authorized reports.', FILTERS)(performance.get_score_trend)
register('compare_periods', 'Compare completed QA results across adjacent equal-length periods ending at date_to.',
          {**{k: v for k, v in FILTERS.items() if k != 'date_from'}, 'days': I('Days per period', 1, 90)})(performance.compare_periods)
register('find_pending_reviews', 'Current outstanding team-leader backlog (including carryover) or pending reports submitted in an explicit period. Default is CURRENT BACKLOG, never silently restrict to recent submissions.',
          {**FILTERS, 'mode': E('current_backlog = all currently outstanding including older reports; submitted_in_period = only reports submitted in date window', ('current_backlog', 'submitted_in_period')), 'older_than_days': I('Minimum days since submission', 0, 365),
           'limit': I('Maximum reports', 1, 50),
           'team_leader_id': S('Team leader UUID returned by lookup_visible_people; always narrows existing access', 36)})(reviews.find_pending_reviews)
register('get_team_leader_review_summary', 'Pending versus acknowledged/closed review counts grouped by assigned team leader.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'team_id': S('Optional team UUID', 36), 'project_name': S('Optional exact project name'),
           'limit': I('Maximum leaders', 1, 50)})(reviews.get_team_leader_review_summary)
register('find_overdue_reviews', 'Pending team-leader QA reports older than a specified SLA; excludes reports not yet submitted.',
          {**FILTERS, 'older_than_hours': I('Hours since submission', 1, 720),
           'limit': I('Maximum overdue reports', 1, 50)}, ('older_than_hours',))(reviews.find_overdue_reviews)
register('get_review_details', 'Get verifiable scorecard results, recorded critical errors and workflow state for ONE authorized review ID.',
          {'review_id': S('Exact review UUID', 36)}, ('review_id',))(reviews.get_review_details)
register('list_recent_reviews', 'Recent authorized submitted reviews with IDs, scores, agents and leader review status.',
          {**FILTERS, 'limit': I('Maximum reports', 1, 50)})(reviews.list_recent_reviews)
register('get_critical_error_summary', 'Count types of critical errors in completed authorized reviews, with some review IDs as evidence.', FILTERS)(recurrence.get_critical_error_summary)
register('find_repeated_mistakes', 'Find dialer agents repeatedly failing the same scored QA criterion or receiving the same critical error across distinct submitted reviews. Dates and scope required for correctness.',
          {**FILTERS, 'minimum_occurrences': I('Min distinct reviews per error', 2, 20),
           'limit': I('Maximum repeated issue groups', 1, 40)})(recurrence.find_repeated_mistakes)
register('find_repeat_critical_errors', 'Identify dialer agents with the SAME critical error on multiple authorized submitted reviews.',
          {**FILTERS, 'minimum_occurrences': I('Minimum reviews', 2, 20), 'limit': I('Maximum rows', 1, 40)})(recurrence.find_repeat_critical_errors)
register('get_criterion_failures', 'Rank QA scorecard subcriteria most often scored below their maximum on submitted reviews.',
          {**FILTERS, 'limit': I('Maximum criteria', 1, 40)})(recurrence.get_criterion_failures)
register('get_coaching_backlog', 'Count QA reports in coaching-planned state or with overdue coaching due dates.',
          {**FILTERS, 'limit': I('Maximum reports', 1, 50)})(reviews.get_coaching_backlog)
register('get_review_workflow_events', 'Recent workflow event types, dates, responsible actors for ONE authorized review. Excludes free-form notes.',
          {'review_id': S('Exact review UUID', 36), 'limit': I('Maximum events', 1, 30)}, ('review_id',))(reviews.get_review_workflow_events)

# V3 organizational directory: no raw account search or cross-tenant identifiers.
register('lookup_visible_people', 'Look up authorized team leaders or dialer agents by natural name. ALWAYS use before filtering by a named leader; do not assume a leader is an agent.',
         {'search': S('Person name or agent username', 120),
          'role': E('Expected organizational role, or any to search both', ('any','team_leader','agent')),
          'limit': I('Maximum matches', 1, 15)}, ('search',))(lookup_visible_people)

# Narrow, authorized context and call-library tools for V3.
register('list_visible_dialers', 'Resolve real dialer names/UUIDs separately from project names. Useful for ArenaMedicare dialer requests and fuzzy spelling.',
         {**DATES, 'search': S('Optional dialer name or approximate spelling', 120), 'limit': I('Maximum matches', 1, 30)})(context.list_visible_dialers)
register('get_call_library_overview', 'Count Call Library entries received in a date range using the same permissions as the Call Library UI; includes calls without QA reviews.',
         {**DATES, 'dialer_id': S('Authorized dialer UUID, if requested', 36)})(context.get_call_library_overview)
register('get_review_qa_context', 'For ONE visible QA review, return structured headings/subheadings, applicability, criterion scores, critical errors and redacted reviewer-written recommendations.',
         {'review_id': S('Exact authorized review UUID', 36)}, ('review_id',))(context.get_review_qa_context)
register('get_qa_feedback_examples', 'Limited examples of real QA reviewer improvements, expected behavior and coaching suggestions from accessible completed reports. This is NOT an aggregate trend.',
         {**FILTERS, 'limit': I('Maximum example reports', 1, 8)})(context.get_qa_feedback_examples)

register('get_agent_critical_violations', 'For a named agent, obtain the exact explicitly recorded critical violation types and verifiable review IDs, not only aggregate counts. Exact name or dialer username; ask to disambiguate duplicate identities.',
         {**DATES, 'search': S('Exact agent username or display name', 120),
          'dialer_id': S('Optional authorized dialer UUID for duplicate names', 36),
          'project_name': S('Exact project name if scoped'),
          'team_id': S('Optional team UUID', 36),
          'limit': I('Maximum linked reviews', 1, 20)}, ('search',))(recurrence.get_agent_critical_violations)
