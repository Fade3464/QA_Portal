"""Provider-neutral semantic planning: model proposes meaning; Django validates and executes.

No SQL, role, org permissions, or arbitrary tool names are accepted from the model.
A small deterministic fallback is used only when a model declines the planning tool.
"""
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from django.utils import timezone
from rest_framework.exceptions import ValidationError

INTENTS = ('review_backlog', 'review_compliance', 'recurring_mistakes', 'critical_errors',
           'qa_overview', 'performance_trend', 'performance_change', 'team_ranking',
           'agent_performance', 'project_performance', 'coaching_backlog', 'review_details',
           'agent_lookup', 'team_lookup', 'project_lookup', 'policy', 'unknown')
PERIODS = ('this_week', 'last_week', 'last_30_days', 'this_month', 'custom')

PLAN_TOOL = {'type': 'function', 'function': {
    'name': 'submit_query_plan',
    'description': 'Submit one semantic QA analytics plan. This proposes a business meaning, not database access or a security scope.',
    'parameters': {'type': 'object', 'additionalProperties': False,
        'properties': {
            'intent': {'type': 'string', 'enum': list(INTENTS)},
            'period': {'type': 'string', 'enum': list(PERIODS)},
            'backlog_mode': {'type': 'string', 'enum': ['current_backlog','submitted_in_period']},
            'company_name': {'type': 'string', 'maxLength': 120},
            'branch_name': {'type': 'string', 'maxLength': 120},
            'project_name': {'type': 'string', 'maxLength': 120},
            'team_name': {'type': 'string', 'maxLength': 120},
            'agent_name': {'type': 'string', 'maxLength': 120},
            'review_id': {'type': 'string', 'maxLength': 36},
            'date_from': {'type': 'string', 'maxLength': 10},
            'date_to': {'type': 'string', 'maxLength': 10},
        }, 'required': ['intent','period']}
}}

PLANNER_PROMPT = """You interpret informal CallLens QA management questions. Respond with ONLY
submit_query_plan tool call. Do not answer the question or invent facts.
- For 'who hasn't checked their reports this week?' or 'pending reviews this week',
  choose review_backlog/current_backlog; the week describes the submitted cohort,
  but include older currently pending reviews too. If explicitly 'only reports submitted
  this week', choose submitted_in_period.
- 'Who is falling behind?' about review status -> review_backlog.
- 'Repeated errors again' -> recurring_mistakes. 'Why did quality drop?' -> performance_change.
- Do NOT set team_name to generic 'team leaders' or 'my team'; only use explicit proper names.
- For natural followups, use conversation context. Never invent team UUIDs, agent usernames,
  project names, review IDs or dates. Only supply identifying hints explicitly mentioned.
- If the question names a company/branch, copy those names exactly as hints for Django
  to resolve WITHIN the user's authorized scope. Never set an access role or UUID scope; Django provides those. If question is unrelated, intent unknown.
- 'this week' means this calendar week, 'last week' previous calendar week.
- Pending backlog is a CURRENT state. The week is NOT a historical state snapshot.
"""

@dataclass(frozen=True)
class QueryPlan:
    intent: str
    period: str = 'last_30_days'
    backlog_mode: str = 'current_backlog'
    company_name: str = ''
    branch_name: str = ''
    project_name: str = ''
    team_name: str = ''
    agent_name: str = ''
    review_id: str = ''
    date_from: str = ''
    date_to: str = ''

    def dates(self):
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        if self.period == 'this_week':
            return monday.isoformat(), today.isoformat()
        if self.period == 'last_week':
            return (monday-timedelta(days=7)).isoformat(), (monday-timedelta(days=1)).isoformat()
        if self.period == 'this_month':
            return today.replace(day=1).isoformat(), today.isoformat()
        if self.period == 'last_30_days':
            return (today-timedelta(days=29)).isoformat(), today.isoformat()
        if self.period == 'custom':
            from apps.analytics.services.core import _dates
            first, last = _dates(self.date_from, self.date_to)
            if not self.date_from or not self.date_to:
                raise ValidationError({'period': 'Both custom dates are required.'})
            return first.isoformat(), last.isoformat()
        raise ValidationError({'period': 'Unsupported period.'})

    def public_metadata(self):
        return {'intent': self.intent, 'period': self.period,
                'backlog_mode': self.backlog_mode if self.intent == 'review_backlog' else None,
                'date_from': self.dates()[0], 'date_to': self.dates()[1],
                'company': self.company_name or None, 'branch': self.branch_name or None,
                'project': self.project_name or None, 'team': self.team_name or None,
                'agent': self.agent_name or None}


def _validated(raw):
    if not isinstance(raw, dict) or set(raw) - set(PLAN_TOOL['function']['parameters']['properties']):
        raise ValidationError('Invalid planner fields.')
    for name in ('intent','period','backlog_mode'):
        if name in raw and not isinstance(raw[name], str):
            raise ValidationError('Invalid planner type.')
    if raw.get('intent') not in INTENTS or raw.get('period') not in PERIODS:
        raise ValidationError('Unsupported planner intent or period.')
    if raw.get('backlog_mode','current_backlog') not in ('current_backlog','submitted_in_period'):
        raise ValidationError('Unsupported backlog mode.')
    for key in ('company_name','branch_name','project_name','team_name','agent_name','date_from','date_to','review_id'):
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value) > (10 if key.startswith('date_') else 120):
            raise ValidationError('Invalid planner detail.')
    if raw.get('review_id'):
        try:
            UUID(raw['review_id'])
        except ValueError as exc:
            raise ValidationError('Invalid review ID.') from exc
    plan = QueryPlan(**raw)
    plan.dates()  # Validate date range, even if no ORM query will run.
    return plan


def _fallback(text, previous=None):
    """Safe degraded behavior only; avoid treating a guessing classifier as truth."""
    q = text.casefold()
    period = ('last_week' if 'last week' in q else 'this_week' if 'this week' in q
              else 'this_month' if 'this month' in q else 'last_30_days')
    if any(word in q for word in ('pending', 'unreviewed', 'backlog', 'behind on review', 'haven\'t reviewed', 'not reviewed', 'overdue', 'late review', 'behind on their reviews')):
        return QueryPlan(intent='review_backlog', period=period,
                         backlog_mode='submitted_in_period' if 'only submitted' in q else 'current_backlog')
    if any(word in q for word in ('repeated', 'same mistake', 'repeat offender', 'keeps making', 'again')):
        return QueryPlan(intent='recurring_mistakes', period=period)
    if any(word in q for word in ('critical error', 'critical mistake')):
        return QueryPlan(intent='critical_errors', period=period)
    if any(word in q for word in ('performance', 'score', 'quality')):
        return QueryPlan(intent='performance_trend', period=period)
    if previous and q.strip() in ('what about last week?', 'and last week?', 'what about this week?'):
        new_period = 'last_week' if 'last week' in q else 'this_week'
        saved = {k:v for k,v in previous.items() if k in QueryPlan.__dataclass_fields__}
        saved['period'] = new_period
        return _validated(saved)
    return QueryPlan(intent='unknown', period=period)


def plan_question(provider, question, history=(), previous=None):
    context = [f"Previous verified intent: {json.dumps(previous, ensure_ascii=False)[:450]}"] if previous else []
    context.extend(f"{m.get('role','user')}: {str(m.get('content',''))[:450]}" for m in list(history)[-3:])
    messages = [
        {'role': 'system', 'content': PLANNER_PROMPT},
        {'role': 'user', 'content': '\n'.join(context + ['Current question: '+question])},
    ]
    completion = provider.complete(messages, [PLAN_TOOL])
    for call in completion.message.get('tool_calls') or []:
        if call.get('type') != 'function' or call.get('function', {}).get('name') != 'submit_query_plan':
            continue
        try:
            arguments = call['function']['arguments']
            if not isinstance(arguments,str) or len(arguments) > 2500:
                continue
            return _validated(json.loads(arguments))
        except (ValueError, TypeError, KeyError, ValidationError):
            continue
    return _fallback(question, previous)
