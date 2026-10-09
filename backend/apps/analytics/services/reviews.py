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

def find_pending_reviews(*, user, mode='current_backlog', older_than_days=0, limit=20,
                         date_from=None, date_to=None, company_id=None, branch_id=None,
                         team_id=None, project_name=None, agent_user=None, dialer_id=None,
                         team_leader_id=None, all_time=False):
    """Current-state backlog with an explicit, optional submission cohort.

    Collection totals and leader breakdown use EXACTLY the same scoped queryset.
    An all-time request has no implicit lower bound or fictitious 30-day cohort.
    A cohort's newer records are not incorrectly called older carryover.
    """
    if mode not in {'current_backlog', 'submitted_in_period'}:
        raise ValidationError({'mode': 'Unsupported backlog interpretation.'})
    if all_time and (date_from or date_to):
        raise ValidationError({'dates': 'all_time cannot have a date interval.'})
    filters = dict(company_id=company_id, branch_id=branch_id, team_id=team_id,
                   project_name=project_name, agent_user=agent_user, dialer_id=dialer_id)
    qs = _base(user, all_time=True, **filters).filter(leader_status=Review.LeaderStatus.PENDING)
    if team_leader_id:
        qs = qs.filter(team_leader_id=_uuid(team_leader_id, 'team_leader_id'))
    today = timezone.localdate()
    start, end = (None, None) if all_time else (
        _dates(date_from, date_to) if date_from or date_to else
        (today - timedelta(days=today.weekday()), today))
    cohort_q = Q() if all_time else Q(completed_at__date__gte=start, completed_at__date__lte=end)
    if mode == 'submitted_in_period' and not all_time:
        qs = qs.filter(cohort_q)
    if older_than_days:
        qs = qs.filter(completed_at__lte=timezone.now()-timedelta(days=older_than_days))
    cutoff = timezone.now()-timedelta(hours=48)
    totals = qs.aggregate(total=Count('pk'), overdue=Count('pk', filter=Q(completed_at__lt=cutoff)),
                          unassigned=Count('pk', filter=Q(team_leader__isnull=True)))
    cohort_count = qs.filter(cohort_q).count()
    carryover = qs.filter(completed_at__date__lt=start).count() if start else 0
    later_count = qs.filter(completed_at__date__gt=end).count() if end else 0
    unknown_count = qs.filter(completed_at__isnull=True).count()
    groups = (qs.order_by().values('team_leader_id','team_leader__first_name','team_leader__last_name')
              .annotate(pending=Count('pk'), overdue=Count('pk', filter=Q(completed_at__lt=cutoff)),
                        newly_submitted=Count('pk', filter=cohort_q),
                        carried=Count('pk', filter=Q(completed_at__date__lt=start)) if start else Count('pk', filter=Q(pk__isnull=True)))
              .order_by('-pending', 'team_leader_id'))
    group_count = qs.order_by().values('team_leader_id').distinct().count()
    leaders = [{'team_leader_id': str(item['team_leader_id']) if item['team_leader_id'] else None,
                'name': ' '.join(filter(None, (item['team_leader__first_name'], item['team_leader__last_name']))) or 'Unassigned',
                'pending': item['pending'], 'overdue': item['overdue'],
                'submitted_in_period': item['newly_submitted'],
                'outside_period': item['pending']-item['newly_submitted'],
                'carried_over': item['carried']}
               for item in groups[:60]]
    results = list(qs.order_by('completed_at','pk')[:limit])
    return {
        'definition': 'Currently pending TL acknowledgement for submitted QA evaluations; not QA analyst drafts.',
        'interpretation': mode,
        'period': {'date_from': start.isoformat() if start else None,
                   'date_to': end.isoformat() if end else None, 'all_time': all_time,
                   'date_field': 'completed_at', 'timezone': str(timezone.get_current_timezone())},
        'as_of': timezone.now().isoformat(),
        'total_pending': totals['total'], 'submitted_in_period_pending': cohort_count,
        'carried_over': carryover, 'submitted_after_period_pending': later_count,
        'missing_submission_date': unknown_count, 'overdue_48h': totals['overdue'],
        'unassigned': totals['unassigned'], 'leaders': leaders,
        'reports': [{'review_id': str(r.pk),
                     'team_leader_id': str(r.team_leader_id) if r.team_leader_id else None,
                     'team_leader_name': r.team_leader.full_name if r.team_leader_id else 'Unassigned',
                     'team_id': str(r.call.team_id) if r.call.team_id else None,
                     'agent': _agent(r),
                     'completed_at': r.completed_at.isoformat() if r.completed_at else None}
                    for r in results],
        'returned': len(results), 'leader_count': group_count,
        'completeness': {'aggregate_complete': True, 'detail_truncated': totals['total'] > len(results),
                         'leader_breakdown_truncated': group_count > 60},
        'warnings': ['Leader grouping is limited to the first 60 leaders.'] if group_count > 60 else [],
    }


def get_team_leader_review_summary(*, user, limit=30, **kwargs):
    qs = _base(user, **kwargs)
    rows = (qs.values('team_leader_id', 'team_leader__first_name', 'team_leader__last_name')
            .annotate(total=Count('pk'), pending=Count('pk', filter=Q(leader_status=Review.LeaderStatus.PENDING)),
                      reviewed=Count('pk', filter=Q(leader_status__in=[Review.LeaderStatus.ACKNOWLEDGED,
                                     Review.LeaderStatus.COACHING_PLANNED, Review.LeaderStatus.COACHING_COMPLETED,
                                     Review.LeaderStatus.ESCALATED, Review.LeaderStatus.CLOSED])))
            .order_by('-pending', '-total')[:limit])
    return {'leaders': [{'team_leader_id': str(r['team_leader_id']) if r['team_leader_id'] else None,
             'name': ' '.join(filter(None, [r['team_leader__first_name'], r['team_leader__last_name']])) or 'Unassigned',
             'total': r['total'], 'pending': r['pending'], 'reviewed_or_progressed': r['reviewed']}
            for r in rows], 'definition': 'Returned-to-QA and other non-pending statuses are not counted as reviewed.'}


def find_overdue_reviews(*, user, older_than_hours, limit=25, **kwargs):
    qs = _base(user, **kwargs).filter(leader_status=Review.LeaderStatus.PENDING,
                                    completed_at__lte=timezone.now() - timedelta(hours=older_than_hours))
    return {'overdue_count': qs.count(), 'reports': [{'review_id': str(r.pk),
             'team_leader_id': str(r.team_leader_id) if r.team_leader_id else None,
             'submitted_at': r.completed_at.isoformat(), 'agent': _agent(r)}
            for r in qs.order_by('completed_at')[:limit]]}


def get_review_details(*, user, review_id):
    review = permitted_reviews(user).filter(pk=_uuid(review_id, 'review_id')).first()
    if not review:
        # Avoid an authorization oracle: no distinction between missing and invisible.
        return {'found': False}
    return {'found': True, 'review_id': str(review.pk), 'score': _number(review.score),
            'evaluation_type': review.evaluation_type, 'status': review.status,
            'leader_status': review.leader_status, 'agent': _agent(review),
            'team_leader_id': str(review.team_leader_id) if review.team_leader_id else None,
            'completed_at': review.completed_at.isoformat() if review.completed_at else None,
            'scorecard_version': review.scorecard_version, 'scores': review.scores,
            'criterion_applicability': review.criterion_applicability,
            'critical_errors': [{'key': k, 'label': ERROR_LABELS.get(k, k)} for k in review.critical_errors],
            'coaching_due_at': review.coaching_due_at.isoformat() if review.coaching_due_at else None,
            'privacy': 'Customer phone numbers, recording URLs, raw payloads and notes intentionally excluded.'}


def list_recent_reviews(*, user, limit=20, **kwargs):
    qs = _period(user, **kwargs)
    return {'total': qs.count(), 'reports': [
        {'review_id': str(r.pk), 'agent': _agent(r), 'score': _number(r.score),
         'critical_errors': r.critical_errors, 'leader_status': r.leader_status,
         'completed_at': r.completed_at.isoformat() if r.completed_at else None}
        for r in qs.order_by('-completed_at')[:limit]]}


def get_coaching_backlog(*, user, limit=20, **kwargs):
    qs = _period(user, **kwargs).filter(leader_status=Review.LeaderStatus.COACHING_PLANNED)
    overdue = qs.filter(coaching_due_at__lt=timezone.now())
    return {'coaching_planned': qs.count(), 'overdue': overdue.count(),
            'reports': [{'review_id': str(r.pk), 'agent': _agent(r),
                         'coaching_due_at': r.coaching_due_at.isoformat() if r.coaching_due_at else None}
                        for r in overdue.order_by('coaching_due_at')[:limit]]}


def get_review_workflow_events(*, user, review_id, limit=15):
    review = permitted_reviews(user).filter(pk=_uuid(review_id, 'review_id')).first()
    if not review:
        return {'found': False}
    events = review.workflow_events.select_related('actor').order_by('-created_at')[:limit]
    return {'found': True, 'review_id': str(review.pk), 'events': [
        {'event_type': e.event_type, 'from_status': e.from_status, 'to_status': e.to_status,
         'actor_name': e.actor.full_name, 'created_at': e.created_at.isoformat()}
        for e in events]}
