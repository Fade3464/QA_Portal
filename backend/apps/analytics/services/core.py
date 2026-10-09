"""Canonical CallLens QA business analytics, independent of any LLM transport."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.calls.models import Review
from apps.calls.scorecard import CRITICAL_ERRORS, SCORECARD, scorecard_payload
from apps.access.policy import permitted_management_reviews as permitted_reviews

COMPLETE = (Review.Status.COMPLETED, Review.Status.DISPUTED)
ERROR_LABELS = dict(CRITICAL_ERRORS)
CRITERIA = {key: (label, maximum, group['key'], group['label'])
            for group in SCORECARD for key, label, maximum in group['criteria']}
SCAN_LIMIT = 3000


def _dates(date_from=None, date_to=None):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(date_from) if date_from else today - timedelta(days=29)
        end = date.fromisoformat(date_to) if date_to else today
    except (TypeError, ValueError) as exc:
        raise ValidationError({'dates': 'Use valid YYYY-MM-DD dates.'}) from exc
    if start > end or (end - start).days > 365:
        raise ValidationError({'dates': 'Date range must be ordered and at most 366 days inclusive.'})
    return start, end

def _uuid(value, label):
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({label: 'Expected a valid UUID.'}) from exc

def _base(user, *, date_from=None, date_to=None, company_id=None, branch_id=None,
          team_id=None, project_name=None, agent_user=None, dialer_id=None, completed=True, date_field=None, all_time=False):
    qs = permitted_reviews(user)
    if completed:
        qs = qs.filter(status__in=COMPLETE)
    if company_id:
        qs = qs.filter(call__branch__company_id=_uuid(company_id, 'company_id'))
    if branch_id:
        qs = qs.filter(call__branch_id=_uuid(branch_id, 'branch_id'))
    if team_id:
        qs = qs.filter(call__team_id=_uuid(team_id, 'team_id'))
    if dialer_id:
        qs = qs.filter(call__dialer_id=_uuid(dialer_id, 'dialer_id'))
    if project_name:
        qs = qs.filter(project_name__iexact=project_name.strip())
    if agent_user:
        qs = qs.filter(call__agent_user__iexact=agent_user.strip())
    if all_time:
        return qs
    start, end = _dates(date_from, date_to)
    field = date_field or ('completed_at' if completed else 'assigned_at')
    return qs.filter(**{f'{field}__date__gte': start, f'{field}__date__lte': end})

def _number(value):
    return round(float(value), 2) if value is not None else None

def _agent_key(row):
    # Agent user IDs are dialer-specific, not portal User foreign keys.
    username = (row.call.agent_user or '').strip()
    if not username:
        return None
    return (str(row.call.dialer_id), username.casefold())

def _agent(row):
    return {'agent_user': row.call.agent_user, 'agent_name': row.call.agent_name or row.call.agent_user,
            'dialer_id': str(row.call.dialer_id), 'team_id': str(row.call.team_id) if row.call.team_id else None}

def _read_rows(qs, *, limit=SCAN_LIMIT):
    # Reject oversized requests instead of silently reporting false rankings from partial data.
    rows = list(qs.order_by('-completed_at', '-pk')[:limit + 1])
    if len(rows) > limit:
        raise ValidationError({'scope': f'Too many evaluations (> {limit}). Narrow the date, project or team.'})
    return rows

def _evidence(row):
    return {'review_id': str(row.pk), 'completed_at': row.completed_at.isoformat() if row.completed_at else None}

def _period(user, *, date_from=None, date_to=None, company_id=None, branch_id=None, team_id=None, project_name=None, agent_user=None, dialer_id=None):
    return _base(user, date_from=date_from, date_to=date_to, company_id=company_id,
                 branch_id=branch_id, team_id=team_id, project_name=project_name, agent_user=agent_user, dialer_id=dialer_id)

def _summary(qs):
    stats = qs.aggregate(total=Count('pk'), scored=Count('pk', filter=Q(score__isnull=False)),
                         avg_score=Avg('score'), critical_reviews=Count('pk', filter=~Q(critical_errors=[])),
                         below_benchmark=Count('pk', filter=Q(score__lt=85)),
                         partial_calls=Count('pk', filter=Q(evaluation_type=Review.EvaluationType.PARTIAL)))
    return {'evaluations': stats['total'], 'scored': stats['scored'], 'average_score': _number(stats['avg_score']),
            'critical_error_reviews': stats['critical_reviews'], 'below_85': stats['below_benchmark'],
            'partial_calls': stats['partial_calls']}

def _date_args(date_from=None, date_to=None):
    start, end = _dates(date_from, date_to)
    return {'date_from': start.isoformat(), 'date_to': end.isoformat()}
