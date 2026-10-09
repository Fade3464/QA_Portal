"""Canonical CallLens QA business analytics, independent of any LLM transport."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.calls.models import Review
from apps.calls.scorecard import CRITICAL_ERRORS, SCORECARD, scorecard_payload
from apps.access.policy import permitted_management_reviews as permitted_reviews

from .core import (
    COMPLETE, ERROR_LABELS, CRITERIA, SCAN_LIMIT, _dates, _uuid, _base, _number, _agent_key, _agent, _read_rows, _evidence, _period, _summary, _date_args
)

def get_qa_overview(*, user, **kwargs):
    return {'period': _date_args(kwargs.get('date_from'), kwargs.get('date_to'), kwargs.get('all_time', False)),
            'metrics': _summary(_period(user, **kwargs))}


def get_agent_performance(*, user, **kwargs):
    return {'agent_user': kwargs['agent_user'], 'metrics': _summary(_period(user, **kwargs)),
            'identity_note': 'Dialer usernames can be reused across dialers; add a team/project filter if needed.'}


def get_team_performance(*, user, **kwargs):
    return {'team_id': kwargs['team_id'], 'metrics': _summary(_period(user, **kwargs))}


def get_project_performance(*, user, **kwargs):
    return {'project_name': kwargs['project_name'], 'metrics': _summary(_period(user, **kwargs))}


def rank_agents(*, user, metric, limit=10, order='worst', **kwargs):
    if metric not in {'average_score', 'critical_error_reviews', 'evaluation_count'} or order not in {'best', 'worst'}:
        raise ValidationError({'ranking': 'Unsupported ranking metric/direction.'})
    qs = _period(user, **kwargs).exclude(call__agent_user='')
    rows = (qs.values('call__dialer_id', 'call__agent_user')
            .annotate(agent_name=Max('call__agent_name'), evaluations=Count('pk'), scored=Count('pk', filter=Q(score__isnull=False)),
                      average_score=Avg('score'), critical_error_reviews=Count('pk', filter=~Q(critical_errors=[]))))
    if metric == 'average_score':
        rows = rows.filter(scored__gte=3).order_by('-average_score' if order == 'best' else 'average_score', '-scored', 'call__agent_user', 'call__dialer_id')
    else:
        descending = order == ('best' if metric == 'evaluation_count' else 'worst')
        rows = rows.order_by(('-' if descending else '') + ('evaluations' if metric == 'evaluation_count' else metric), 'call__agent_user', 'call__dialer_id')
    return {'metric': metric, 'order': order, 'entity_type': 'agent', 'min_evaluations_for_score': 3,
            'total_eligible': rows.count(), 'limit': limit,
            'agents': [{'dialer_id': str(r['call__dialer_id']), 'agent_user': r['call__agent_user'],
                        'agent_name': r['agent_name'], 'evaluations': r['evaluations'],
                        'scored': r['scored'], 'average_score': _number(r['average_score']),
                        'critical_error_reviews': r['critical_error_reviews']} for r in rows[:limit]]}


def rank_teams(*, user, metric, limit=10, order='worst', **kwargs):
    """Team identity stays a team UUID. No fallback to an agent error table."""
    if metric not in {'average_score', 'critical_error_reviews', 'evaluation_count'} or order not in {'best', 'worst'}:
        raise ValidationError({'ranking': 'Unsupported ranking metric/direction.'})
    qs = _base(user, **kwargs).exclude(call__team__isnull=True)
    rows = (qs.order_by().values('call__team_id', 'call__team__name')
            .annotate(evaluations=Count('pk'), scored=Count('pk', filter=Q(score__isnull=False)),
                      average_score=Avg('score'),
                      critical_error_reviews=Count('pk', filter=~Q(critical_errors=[]))))
    field = 'evaluations' if metric == 'evaluation_count' else metric
    if metric == 'average_score':
        rows = rows.filter(scored__gte=3)
    descending = (order == 'best') if metric in {'average_score', 'evaluation_count'} else (order == 'worst')
    rows = rows.order_by(('-' if descending else '') + field, 'call__team_id')
    total = rows.count()
    result = [{'team_id': str(r['call__team_id']), 'name': r['call__team__name'],
               'evaluations': r['evaluations'], 'scored': r['scored'],
               'average_score': _number(r['average_score']),
               'critical_error_reviews': r['critical_error_reviews']} for r in rows[:limit]]
    return {'metric': metric, 'order': order, 'entity_type': 'team',
            'min_evaluations_for_score': 3, 'teams': result,
            'total_eligible': total, 'returned': len(result),
            'completeness': {'aggregate_complete': True, 'detail_truncated': total > len(result)}}


def get_score_trend(*, user, **kwargs):
    qs = _period(user, **kwargs)
    missing = qs.filter(completed_at__isnull=True).count()
    rows = list(qs.exclude(completed_at__isnull=True).annotate(day=TruncDate('completed_at'))
            .values('day').annotate(evaluations=Count('pk'), average_score=Avg('score'))
            .order_by('day')[:367])
    if len(rows) > 366:
        raise ValidationError({'period': 'Daily trend exceeds 366 days; choose a shorter interval.'})
    return {'daily': [{'date': r['day'].isoformat(), 'evaluations': r['evaluations'],
                       'average_score': _number(r['average_score'])} for r in rows],
            'missing_submission_date': missing,
            'warnings': ['Reviews without submission dates cannot be placed on the daily trend.'] if missing else []}


def compare_periods(*, user, days=7, **kwargs):
    if kwargs.get('all_time'):
        raise ValidationError({'period': 'A comparison needs two bounded date intervals.'})
    end = _dates(None, kwargs.get('date_to'))[1]
    newer_start = end - timedelta(days=days - 1)
    older_end = newer_start - timedelta(days=1)
    older_start = older_end - timedelta(days=days - 1)
    common = {k: kwargs.get(k) for k in ('company_id', 'branch_id', 'team_id', 'project_name', 'agent_user', 'dialer_id')}
    newer = _base(user, date_from=newer_start.isoformat(), date_to=end.isoformat(), **common)
    older = _base(user, date_from=older_start.isoformat(), date_to=older_end.isoformat(), **common)
    a, b = _summary(older), _summary(newer)
    return {'previous_period': {'from': older_start.isoformat(), 'to': older_end.isoformat(), **a},
            'current_period': {'from': newer_start.isoformat(), 'to': end.isoformat(), **b},
            'score_delta_points': round(b['average_score'] - a['average_score'], 2)
                if b['average_score'] is not None and a['average_score'] is not None else None}
