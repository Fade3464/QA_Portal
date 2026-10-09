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

from .core import (
    COMPLETE, ERROR_LABELS, CRITERIA, SCAN_LIMIT, _dates, _uuid, _base, _number, _agent_key, _agent, _read_rows, _evidence, _period, _summary, _date_args
)

def get_scorecard_policy(*, user):
    permitted_reviews(user)  # Role gate, even for policy tool.
    return scorecard_payload()


def list_available_branches(*, user, date_from=None, date_to=None, all_time=False):
    rows = (_base(user, all_time=all_time, date_from=date_from, date_to=date_to)
            .values('call__branch_id', 'call__branch__name', 'call__branch__company_id',
                    'call__branch__company__name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations')[:100])
    return {'branches': [{'company_id': str(r['call__branch__company_id']),
                         'company_name': r['call__branch__company__name'],
                         'branch_id': str(r['call__branch_id']),
                         'branch_name': r['call__branch__name'],
                         'evaluations': r['evaluations']} for r in rows]}


def list_available_teams(*, user, date_from=None, date_to=None, company_id=None, branch_id=None, all_time=False):
    rows = (_base(user, all_time=all_time, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
            .exclude(call__team__isnull=True)
            .values('call__team_id', 'call__team__name', 'call__team__team_leader__first_name',
                    'call__team__team_leader__last_name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations', 'call__team__name')[:80])
    return {'teams': [{'team_id': str(r['call__team_id']), 'name': r['call__team__name'],
                       'team_leader': ' '.join(filter(None, (r['call__team__team_leader__first_name'],
                                                            r['call__team__team_leader__last_name']))),
                       'evaluations': r['evaluations']} for r in rows]}


def list_available_projects(*, user, date_from=None, date_to=None, company_id=None, branch_id=None, all_time=False):
    rows = (_base(user, all_time=all_time, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
            .exclude(project_name__isnull=True).values('project_name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations')[:100])
    return {'projects': list(rows)}


def find_agents(*, user, search, date_from=None, date_to=None, company_id=None, branch_id=None, limit=15, all_time=False):
    if len(search.strip()) < 2:
        raise ValidationError({'search': 'At least two characters required.'})
    qs = (_base(user, all_time=all_time, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
          .filter(Q(call__agent_user__icontains=search) | Q(call__agent_name__icontains=search))
          .values('call__dialer_id', 'call__agent_user', 'call__agent_name')
          .annotate(evaluations=Count('pk')).order_by('-evaluations')[:limit])
    return {'agents': [{'dialer_id': str(r['call__dialer_id']), 'agent_user': r['call__agent_user'],
                        'agent_name': r['call__agent_name'], 'evaluations': r['evaluations']} for r in qs],
            'note': 'Agent usernames are scoped to their dialer; names are not unique identifiers.'}
