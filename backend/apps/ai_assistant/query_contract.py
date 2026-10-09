"""Provider-neutral meaning of ONE turn, separate from tool selection and permissions.

The LLM proposes semantics for open language. Explicit subject/direction constraints
in the current user turn take precedence over that proposal and stale conversation
state. A query contract is NOT authorization: the domain services still scope every
query to the authenticated user. This module has no database/provider dependencies.
"""
from dataclasses import dataclass, field
import re

SUBJECTS = {'agent', 'team', 'team_leader', 'project', 'dialer', 'call', 'review', 'policy', 'unknown'}
OPERATIONS = {'ranking', 'backlog', 'summary', 'repeated_criteria', 'repeated_critical',
              'critical_details', 'critical_summary', 'discovery', 'other'}
METRICS = {'average_score', 'critical_error_reviews', 'evaluation_count'}
SCOPE_KEYS = ('company_id', 'branch_id', 'team_id', 'project_name', 'agent_user', 'dialer_id', 'team_leader_id')
PRIMARY = {'repeated_criteria': 'find_repeated_mistakes', 'repeated_critical': 'find_repeat_critical_errors',
           'critical_details': 'get_agent_critical_violations', 'critical_summary': 'get_critical_error_summary'}
INTENTS = {'agent_ranking': ('agent', 'ranking'), 'team_ranking': ('team', 'ranking'),
           'leader_backlog': ('team_leader', 'backlog'), 'review_backlog': ('team_leader', 'backlog'),
           'repeated_criteria': ('agent', 'repeated_criteria'), 'repeated_critical': ('agent', 'repeated_critical'),
           'agent_violation_details': ('agent', 'critical_details'), 'qa_summary': ('review', 'summary'),
           'critical_summary': ('review', 'critical_summary'), 'call_volume': ('call', 'summary')}

def _has(q, pattern):
    return bool(re.search(pattern, q, re.I))


def explicit_subject(text):
    # Roles must be checked before the word team. Review workflow also differs
    # from employee QA performance. A scoped phrase "agents in my team" is AGENT.
    q = text.casefold()
    if _has(q, r'\b(?:team[ -]?leaders?|tls?|supervisors?|project managers?)\b'):
        return 'team_leader'
    if _has(q, r'\b(?:agents?|performers?|guys?)\b'):
        return 'agent'
    if _has(q, r'\bteams?\b'):
        return 'team'
    if _has(q, r'\b(?:call library|incoming calls|calls received|calls arrived)\b'):
        return 'call'
    if _has(q, r'\bdialers?\b'):
        return 'dialer'
    if _has(q, r'\bprojects?\b'):
        return 'project'
    return None


def explicit_order(text):
    if _has(text, r'\b(?:best|strongest|highest[ -]scor\w*|top[ -]perform\w*)\b'):
        return 'best'
    if _has(text, r'\b(?:worst|weakest|lowest[ -]scor\w*|underperform\w*)\b'):
        return 'worst'
    if _has(text, r'\b(?:fewest|least|lowest)\b') and _has(text, r'\b(?:errors?|violations?|problems?|pending)\b'):
        return 'best'
    if _has(text, r'\b(?:most|highest|largest)\b') and _has(text, r'\b(?:errors?|violations?|problems?|pending)\b'):
        return 'worst'
    return None


def referential(text):
    return _has(text, r"^\s*(?:and\b|what about\b|how about\b|of (?:them|those)\b)|\b(?:next|others?|remaining|second|third|fourth|fifth|\d+(?:st|nd|rd|th)|his|her|their|same|those|them)\b")


def named_reference(text, selection=None):
    """Only accept a model's name if it is literally present in the user turn.

    Approximate names are never turned into IDs here. The authorized directory
    must resolve them, and ask for confirmation on suggestions/ambiguity.
    """
    selected = (selection or {}).get('entity_name')
    if isinstance(selected, str) and 1 < len(selected.strip()) <= 120:
        name = selected.strip()
        if name.casefold() in text.casefold() and name.casefold() not in {'all', 'our', 'my', 'the team', 'the agents'}:
            return name
    # Safe fallback only for an explicit person target, not every prepositional
    # phrase ("for all time" / "in the past 10 days" are NOT people).
    m = re.search(r'\b(?:for|by|about|of)\s+([\w][\w .@\-]{1,100}?)(?:[?!.]|$)', text, re.I)
    if m:
        name = m.group(1).strip()
        name = re.split(r'\s+(?:this|last|past|over|during|in the|for the|since)\b', name, flags=re.I)[0].strip()
        if name and not _has(name, r'^(?:all|our|my|the|a|an|this|last|past|each|every|any|today|yesterday)\b'):
            return name
    return ''


@dataclass(frozen=True)
class QueryContract:
    subject: str = 'unknown'
    operation: str = 'other'
    metric: str | None = None
    order: str = 'worst'
    entity_name: str = ''
    collection: bool = True
    reuse: bool = False
    requested_count: int = 1
    backlog_mode: str = 'current_backlog'
    filters: dict = field(default_factory=dict)
    source: str = 'semantic_plan'

    @property
    def primary_tool(self):
        if self.operation == 'ranking':
            return {'agent': 'rank_agents', 'team': 'rank_teams',
                    'team_leader': 'find_pending_reviews'}.get(self.subject)
        if self.operation == 'backlog':
            return 'find_pending_reviews'
        if self.operation == 'summary':
            return 'get_call_library_overview' if self.subject == 'call' else 'get_qa_overview'
        return PRIMARY.get(self.operation)

    def public(self):
        return {'subject': self.subject, 'operation': self.operation, 'metric': self.metric,
                'order': self.order, 'collection': self.collection, 'entity_name': self.entity_name,
                'requested_count': self.requested_count, 'backlog_mode': self.backlog_mode,
                'source': self.source}

    def state(self, window, filters=None):
        return {**self.public(), 'version': 1, 'filters': dict(filters or self.filters),
                'time_window': window}

    def matches(self, name, args, required_args):
        """A narrowed secondary lookup is not proof of a collection-wide answer."""
        if name != self.primary_tool:
            return False
        keys = set(SCOPE_KEYS) | {'metric', 'order', 'mode', 'all_time', 'date_from', 'date_to', 'search', 'older_than_days'}
        for key in keys:
            actual, needed = args.get(key), required_args.get(key)
            if key == 'all_time':
                if bool(actual) != bool(needed):
                    return False
            elif actual != needed:
                return False
        return True


def previous_contract(previous):
    if not isinstance(previous, dict):
        return {}
    state = previous.get('query_contract', {})
    if isinstance(state, dict) and state.get('version') == 1:
        return state
    # Migrate only known, query-only historical ranking state, never model prose.
    old = previous.get('last_analysis', {})
    if isinstance(old, dict) and old.get('kind') in {'agent_ranking', 'team_ranking'}:
        return {'subject': old['kind'].split('_')[0], 'operation': 'ranking',
                'metric': old.get('metric'), 'order': old.get('order', 'worst'),
                'filters': old.get('filters', {}), 'entity_name': '', 'collection': True}
    return {}


def plan_contract(question, selection=None, previous=None):
    selection = selection or {}
    q = question.casefold().replace('wrost', 'worst')
    prior = previous_contract(previous)
    explicit = explicit_subject(q)
    proposed_subject, proposed_op = INTENTS.get(selection.get('intent'), ('unknown', 'other'))
    if selection.get('subject') in SUBJECTS:
        proposed_subject = selection['subject']
    if selection.get('operation') in OPERATIONS:
        proposed_op = selection['operation']
    reuse = bool(prior and referential(q) and (explicit is None or explicit == prior.get('subject')))
    subject = explicit or (prior.get('subject') if reuse else None) or proposed_subject
    operation = proposed_op
    ranking = _has(q, r'\b(?:best|worst|most|least|highest|lowest|top|bottom|rank\w*|strongest|weakest|underperform\w*)\b')
    workflow = _has(q, r'\b(?:pending|unreviewed|outstanding|backlog|overdue|not reviewed|not reviewing|reviewing|behind on reviews|awaiting review)\b')
    recurrence = _has(q, r'\b(?:repeat\w*|recurring|constantly|again and again)\b')
    critical = _has(q, r'\b(?:critical|violations?)\b')
    if workflow:
        subject, operation = 'team_leader', 'backlog'
    elif recurrence:
        subject, operation = 'agent', ('repeated_critical' if critical else 'repeated_criteria')
    elif critical and _has(q, r'\b(?:recorded|mentioned|critical call|violation for|violation of|violation on)\b') and named_reference(question, selection):
        subject, operation = 'agent', 'critical_details'
    elif ranking and subject in {'agent', 'team', 'team_leader'}:
        operation = 'backlog' if subject == 'team_leader' else 'ranking'
    elif subject == 'call':
        operation = 'summary'
    elif _has(q, r'\b(?:how many|total|count)\b') and _has(q, r'\b(?:evaluations?|reports?|reviews?)\b'):
        operation = 'summary'
        subject = subject if subject in {'project', 'dialer'} else 'review'
    elif critical and _has(q, r'\b(?:how many|total|count|summary|errors?)\b'):
        subject, operation = 'review', 'critical_summary'
    elif reuse and operation == 'other':
        operation = prior.get('operation', 'other')
    # A fresh explicit team cannot inherit an old AGENT primary tool from Qwen.
    if subject == 'team' and operation == 'other' and ranking:
        operation = 'ranking'
    name = named_reference(question, selection) if operation in {'backlog', 'critical_details'} else ''
    if not name and reuse and _has(q, r'\b(?:his|her|him|that leader|same leader|that agent)\b'):
        name = str(prior.get('entity_name', ''))
    # A collection question explicitly resets an earlier person's scope.
    if _has(q, r'\b(?:which|all|every|each)\s+(?:team leaders|tls|teams|agents)\b'):
        name = ''
        reuse = False
    order = explicit_order(q) or (prior.get('order') if reuse else None) or selection.get('order', 'worst')
    if order not in {'best', 'worst'}:
        order = 'worst'
    metric = None
    if operation == 'ranking':
        if _has(q, r'\b(?:critical|violations?|problems?|mistakes?|errors?)\b'):
            metric = 'critical_error_reviews'
        elif _has(q, r'\b(?:score\w*|quality|perform\w*)\b') or subject == 'team':
            metric = 'average_score'
        elif reuse and prior.get('metric') in METRICS:
            metric = prior['metric']
        else:
            metric = selection.get('rank_metric') if selection.get('rank_metric') in METRICS else 'critical_error_reviews'
    count = 10 if _has(q, r'\b(?:top ten|list|summary)\b') else 1
    match = re.search(r'\b(?:top|bottom|first|other)\s+(\d{1,3})\b', q)
    if match:
        count = min(25, max(1, int(match.group(1))))
    mode = 'submitted_in_period' if workflow and _has(q, r'\b(?:only|just)\b.{0,50}\bsubmitted\b|\bsubmitted (?:this|last|in|during|within|over)\b') else 'current_backlog'
    filters = dict(prior.get('filters', {})) if reuse else {}
    filters = {k: v for k, v in filters.items() if k in SCOPE_KEYS and isinstance(v, str) and len(v) <= 160}
    for noun, keys in {'projects?': ('project_name',), 'teams?': ('team_id', 'team_leader_id', 'agent_user'), 'dialers?': ('dialer_id', 'agent_user')}.items():
        if _has(q, r'\b(?:all|every)\s+' + noun + r'\b'):
            for key in keys:
                filters.pop(key, None)
    if not name:
        filters.pop('team_leader_id', None)
    if subject != 'agent' or operation == 'ranking':
        filters.pop('agent_user', None)
    return QueryContract(subject=subject, operation=operation, metric=metric, order=order,
                         entity_name=name, collection=not bool(name), reuse=reuse,
                         requested_count=count, backlog_mode=mode, filters=filters,
                         source='explicit_and_semantic_contract')


def ranking_cursor(previous):
    """Bound legacy/malformed stored state before using it as a row reference."""
    state = previous_contract(previous)
    value = state.get('rank_cursor', 1)
    if isinstance(value, bool):
        return 1
    try:
        return min(25, max(1, int(value)))
    except (ValueError, TypeError, OverflowError):
        return 1
