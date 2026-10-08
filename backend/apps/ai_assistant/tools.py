"""Read-only analytics on the actual Review/CallEvent schema.

Every database query is derived from the established report visibility scope. No SQL,
filesystem, network, customer phone, recordings or other model-selected capabilities.
"""
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
from .access import permitted_reviews
from .registry import register, S, I, E, DATES, FILTERS

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
          team_id=None, project_name=None, agent_user=None, completed=True, date_field=None):
    qs = permitted_reviews(user)
    if completed:
        qs = qs.filter(status__in=COMPLETE)
    if company_id:
        qs = qs.filter(call__branch__company_id=_uuid(company_id, 'company_id'))
    if branch_id:
        qs = qs.filter(call__branch_id=_uuid(branch_id, 'branch_id'))
    if team_id:
        qs = qs.filter(call__team_id=_uuid(team_id, 'team_id'))
    if project_name:
        qs = qs.filter(project_name__iexact=project_name.strip())
    if agent_user:
        qs = qs.filter(call__agent_user__iexact=agent_user.strip())
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


def _period(user, *, date_from=None, date_to=None, company_id=None, branch_id=None, team_id=None, project_name=None, agent_user=None):
    return _base(user, date_from=date_from, date_to=date_to, company_id=company_id,
                 branch_id=branch_id, team_id=team_id, project_name=project_name, agent_user=agent_user)


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


@register('get_scorecard_policy', 'Return the currently configured QA criteria, scoring benchmark and critical-error definitions. This is code-defined policy, not RAG.')
def get_scorecard_policy(*, user):
    permitted_reviews(user)  # Role gate, even for policy tool.
    return scorecard_payload()


@register('list_available_branches', 'Resolve company and branch UUIDs from names appearing in reports accessible to the signed-in user.', DATES)
def list_available_branches(*, user, date_from=None, date_to=None):
    rows = (_base(user, date_from=date_from, date_to=date_to)
            .values('call__branch_id', 'call__branch__name', 'call__branch__company_id',
                    'call__branch__company__name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations')[:100])
    return {'branches': [{'company_id': str(r['call__branch__company_id']),
                         'company_name': r['call__branch__company__name'],
                         'branch_id': str(r['call__branch_id']),
                         'branch_name': r['call__branch__name'],
                         'evaluations': r['evaluations']} for r in rows]}


@register('list_available_teams', 'List team IDs and names represented in reports visible to the signed-in user.', {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36)})
def list_available_teams(*, user, date_from=None, date_to=None, company_id=None, branch_id=None):
    rows = (_base(user, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
            .exclude(call__team__isnull=True)
            .values('call__team_id', 'call__team__name', 'call__team__team_leader__first_name',
                    'call__team__team_leader__last_name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations', 'call__team__name')[:80])
    return {'teams': [{'team_id': str(r['call__team_id']), 'name': r['call__team__name'],
                       'team_leader': ' '.join(filter(None, (r['call__team__team_leader__first_name'],
                                                            r['call__team__team_leader__last_name']))),
                       'evaluations': r['evaluations']} for r in rows]}


@register('list_available_projects', 'List project names with reports visible to the current user.', {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36)})
def list_available_projects(*, user, date_from=None, date_to=None, company_id=None, branch_id=None):
    rows = (_base(user, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
            .exclude(project_name__isnull=True).values('project_name')
            .annotate(evaluations=Count('pk')).order_by('-evaluations')[:100])
    return {'projects': list(rows)}


@register('find_agents', 'Resolve dialer agent usernames and display names within visible reviewed calls; names may be ambiguous.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'search': S('Part of agent display name or dialer username', 80), 'limit': I('Maximum results', 1, 30)}, ('search',))
def find_agents(*, user, search, date_from=None, date_to=None, company_id=None, branch_id=None, limit=15):
    if len(search.strip()) < 2:
        raise ValidationError({'search': 'At least two characters required.'})
    qs = (_base(user, date_from=date_from, date_to=date_to, company_id=company_id, branch_id=branch_id)
          .filter(Q(call__agent_user__icontains=search) | Q(call__agent_name__icontains=search))
          .values('call__dialer_id', 'call__agent_user', 'call__agent_name')
          .annotate(evaluations=Count('pk')).order_by('-evaluations')[:limit])
    return {'agents': [{'dialer_id': str(r['call__dialer_id']), 'agent_user': r['call__agent_user'],
                        'agent_name': r['call__agent_name'], 'evaluations': r['evaluations']} for r in qs],
            'note': 'Agent usernames are scoped to their dialer; names are not unique identifiers.'}


@register('get_qa_overview', 'Aggregated QA scores, volume, critical errors and partial calls for an authorized date/scope.', FILTERS)
def get_qa_overview(*, user, **kwargs):
    return {'period': _date_args(kwargs.get('date_from'), kwargs.get('date_to')),
            'metrics': _summary(_period(user, **kwargs))}


@register('get_agent_performance', 'QA summary for one dialer agent username (optionally within a team or project).',
          FILTERS, ('agent_user',))
def get_agent_performance(*, user, **kwargs):
    return {'agent_user': kwargs['agent_user'], 'metrics': _summary(_period(user, **kwargs)),
            'identity_note': 'Dialer usernames can be reused across dialers; add a team/project filter if needed.'}


@register('get_team_performance', 'QA summary of a team identified by team UUID.',
          FILTERS, ('team_id',))
def get_team_performance(*, user, **kwargs):
    return {'team_id': kwargs['team_id'], 'metrics': _summary(_period(user, **kwargs))}


@register('get_project_performance', 'QA summary for a project name visible to the current user.',
          FILTERS, ('project_name',))
def get_project_performance(*, user, **kwargs):
    return {'project_name': kwargs['project_name'], 'metrics': _summary(_period(user, **kwargs))}


@register('rank_agents', 'Rank dialer agents by average QA score, review volume or number of critical error reviews; minimum 3 scored reviews for score ranking.',
          {**FILTERS, 'metric': E('Ranking metric', ('average_score', 'critical_error_reviews', 'evaluation_count')),
           'limit': I('Maximum agents', 1, 25),
           'order': E('best = highest score/fewest errors; worst = lowest score/most errors', ('best', 'worst'))}, ('metric',))
def rank_agents(*, user, metric, limit=10, order='worst', **kwargs):
    qs = _period(user, **kwargs).exclude(call__agent_user='')
    rows = (qs.values('call__dialer_id', 'call__agent_user', 'call__agent_name')
            .annotate(evaluations=Count('pk'), scored=Count('pk', filter=Q(score__isnull=False)),
                      average_score=Avg('score'), critical_error_reviews=Count('pk', filter=~Q(critical_errors=[]))))
    if metric == 'average_score':
        rows = rows.filter(scored__gte=3).order_by('-average_score' if order == 'best' else 'average_score', '-scored')
    else:
        rows = rows.order_by(('-' if order == 'worst' else '') + ('evaluations' if metric == 'evaluation_count' else metric), 'call__agent_user')
    return {'metric': metric, 'order': order, 'min_evaluations_for_score': 3,
            'agents': [{'dialer_id': str(r['call__dialer_id']), 'agent_user': r['call__agent_user'],
                        'agent_name': r['call__agent_name'], 'evaluations': r['evaluations'],
                        'scored': r['scored'], 'average_score': _number(r['average_score']),
                        'critical_error_reviews': r['critical_error_reviews']} for r in rows[:limit]]}


@register('rank_teams', 'Rank accessible teams by average scored QA percentage or number of completed reviews.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'project_name': S('Exact project name'),
           'metric': E('Ranking metric', ('average_score', 'evaluation_count')),
           'limit': I('Maximum teams', 1, 25),
           'order': E('best or worst', ('best', 'worst'))}, ('metric',))
def rank_teams(*, user, metric, limit=10, order='worst', **kwargs):
    qs = _base(user, **kwargs).exclude(call__team__isnull=True)
    rows = (qs.values('call__team_id', 'call__team__name')
            .annotate(evaluations=Count('pk'), scored=Count('pk', filter=Q(score__isnull=False)), average_score=Avg('score')))
    if metric == 'average_score':
        rows = rows.filter(scored__gte=3).order_by('-average_score' if order == 'best' else 'average_score')
    else:
        rows = rows.order_by('-evaluations' if order == 'worst' else 'evaluations')
    return {'metric': metric, 'order': order, 'teams': [{'team_id': str(r['call__team_id']), 'name': r['call__team__name'],
                'evaluations': r['evaluations'], 'average_score': _number(r['average_score'])} for r in rows[:limit]]}


@register('get_score_trend', 'Daily average QA score and completed-review volume, filtered to authorized reports.', FILTERS)
def get_score_trend(*, user, **kwargs):
    rows = (_period(user, **kwargs).annotate(day=TruncDate('completed_at'))
            .values('day').annotate(evaluations=Count('pk'), average_score=Avg('score'))
            .order_by('day')[:366])
    return {'daily': [{'date': r['day'].isoformat(), 'evaluations': r['evaluations'],
                       'average_score': _number(r['average_score'])} for r in rows]}


@register('compare_periods', 'Compare completed QA results across adjacent equal-length periods ending at date_to.',
          {**{k: v for k, v in FILTERS.items() if k != 'date_from'}, 'days': I('Days per period', 1, 90)})
def compare_periods(*, user, days=7, **kwargs):
    end = _dates(None, kwargs.get('date_to'))[1]
    newer_start = end - timedelta(days=days - 1)
    older_end = newer_start - timedelta(days=1)
    older_start = older_end - timedelta(days=days - 1)
    common = {k: kwargs.get(k) for k in ('company_id', 'branch_id', 'team_id', 'project_name', 'agent_user')}
    newer = _base(user, date_from=newer_start.isoformat(), date_to=end.isoformat(), **common)
    older = _base(user, date_from=older_start.isoformat(), date_to=older_end.isoformat(), **common)
    a, b = _summary(older), _summary(newer)
    return {'previous_period': {'from': older_start.isoformat(), 'to': older_end.isoformat(), **a},
            'current_period': {'from': newer_start.isoformat(), 'to': end.isoformat(), **b},
            'score_delta_points': round(b['average_score'] - a['average_score'], 2)
                if b['average_score'] is not None and a['average_score'] is not None else None}


@register('find_pending_reviews', 'Find submitted reviews not yet acknowledged by their assigned team leaders. This is NOT the QA analyst draft queue.',
          {**FILTERS, 'older_than_days': I('Minimum days since submission', 0, 365),
           'limit': I('Maximum reports', 1, 50)})
def find_pending_reviews(*, user, older_than_days=0, limit=20, **kwargs):
    if kwargs.get('agent_user'):
        pass
    # Apply completion-date boundaries; avoid leaking reports through a separate unscoped TL join.
    qs = _base(user, **kwargs).filter(leader_status=Review.LeaderStatus.PENDING)
    if older_than_days:
        qs = qs.filter(completed_at__lte=timezone.now() - timedelta(days=older_than_days))
    count = qs.count()
    rows = qs.order_by('completed_at', 'pk')[:limit]
    return {'total_pending': count, 'reports': [
        {'review_id': str(r.pk), 'team_leader_id': str(r.team_leader_id) if r.team_leader_id else None,
         'team_leader_name': r.team_leader.full_name if r.team_leader_id else 'Unassigned',
         'team_id': str(r.call.team_id) if r.call.team_id else None,
         'agent': _agent(r), 'completed_at': r.completed_at.isoformat() if r.completed_at else None}
        for r in rows], 'returned': min(count, limit)}


@register('get_team_leader_review_summary', 'Pending versus acknowledged/closed review counts grouped by assigned team leader.',
          {**DATES, 'company_id': S('Company UUID', 36), 'branch_id': S('Branch UUID', 36),
           'team_id': S('Optional team UUID', 36), 'project_name': S('Optional exact project name'),
           'limit': I('Maximum leaders', 1, 50)})
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


@register('find_overdue_reviews', 'Pending team-leader QA reports older than a specified SLA; excludes reports not yet submitted.',
          {**FILTERS, 'older_than_hours': I('Hours since submission', 1, 720),
           'limit': I('Maximum overdue reports', 1, 50)}, ('older_than_hours',))
def find_overdue_reviews(*, user, older_than_hours, limit=25, **kwargs):
    qs = _base(user, **kwargs).filter(leader_status=Review.LeaderStatus.PENDING,
                                    completed_at__lte=timezone.now() - timedelta(hours=older_than_hours))
    return {'overdue_count': qs.count(), 'reports': [{'review_id': str(r.pk),
             'team_leader_id': str(r.team_leader_id) if r.team_leader_id else None,
             'submitted_at': r.completed_at.isoformat(), 'agent': _agent(r)}
            for r in qs.order_by('completed_at')[:limit]]}


@register('get_review_details', 'Get verifiable scorecard results, recorded critical errors and workflow state for ONE authorized review ID.',
          {'review_id': S('Exact review UUID', 36)}, ('review_id',))
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


@register('list_recent_reviews', 'Recent authorized submitted reviews with IDs, scores, agents and leader review status.',
          {**FILTERS, 'limit': I('Maximum reports', 1, 50)})
def list_recent_reviews(*, user, limit=20, **kwargs):
    qs = _period(user, **kwargs)
    return {'total': qs.count(), 'reports': [
        {'review_id': str(r.pk), 'agent': _agent(r), 'score': _number(r.score),
         'critical_errors': r.critical_errors, 'leader_status': r.leader_status,
         'completed_at': r.completed_at.isoformat() if r.completed_at else None}
        for r in qs.order_by('-completed_at')[:limit]]}


@register('get_critical_error_summary', 'Count types of critical errors in completed authorized reviews, with some review IDs as evidence.', FILTERS)
def get_critical_error_summary(*, user, **kwargs):
    rows = _read_rows(_period(user, **kwargs).exclude(critical_errors=[]))
    counter, evidence = Counter(), defaultdict(list)
    for r in rows:
        for key in set(r.critical_errors or []):
            counter[key] += 1
            if len(evidence[key]) < 5:
                evidence[key].append(str(r.pk))
    return {'critical_errors': [{'key': k, 'label': ERROR_LABELS.get(k, k), 'review_count': n,
                                 'review_ids': evidence[k]} for k, n in counter.most_common()],
            'reviews_with_critical_errors': len(rows)}


@register('find_repeated_mistakes', 'Find dialer agents repeatedly failing the same scored QA criterion or receiving the same critical error across distinct submitted reviews. Dates and scope required for correctness.',
          {**FILTERS, 'minimum_occurrences': I('Min distinct reviews per error', 2, 20),
           'limit': I('Maximum repeated issue groups', 1, 40)})
def find_repeated_mistakes(*, user, minimum_occurrences=2, limit=20, **kwargs):
    rows = _read_rows(_period(user, **kwargs))
    found, agents = defaultdict(list), {}
    unknown_agent_count = 0
    for r in rows:
        agent = _agent_key(r)
        if not agent:
            unknown_agent_count += 1
            continue
        agents[agent] = _agent(r)
        keys = set()
        for err in (r.critical_errors or []):
            keys.add(('critical', str(err)))
        for key, score in (r.scores or {}).items():
            if key not in CRITERIA:
                continue
            label, maximum, category, _cat_label = CRITERIA[key]
            if (r.criterion_applicability or {}).get(key) == 'not_reached':
                continue
            if (r.category_applicability or {}).get(category) == 'not_reached':
                continue
            try:
                if Decimal(str(score)) < Decimal(str(maximum)):
                    keys.add(('criterion', key))
            except (ValueError, TypeError, InvalidOperation):
                continue
        for kind, key in keys:
            found[(agent, kind, key)].append(r)
    result = []
    for (agent, kind, key), instances in found.items():
        if len(instances) < minimum_occurrences:
            continue
        result.append({'agent': agents[agent], 'mistake_type': kind, 'mistake_key': key,
                       'mistake_label': ERROR_LABELS.get(key, key) if kind == 'critical' else CRITERIA[key][0],
                       'occurrences': len(instances), 'evidence': [_evidence(r) for r in instances[:8]],
                       'latest_at': instances[0].completed_at.isoformat() if instances[0].completed_at else None})
    result.sort(key=lambda v: (-v['occurrences'], v['mistake_key'], v['agent']['agent_user']))
    return {'repeated_issues': result[:limit], 'matched_groups': len(result),
            'evaluations_examined': len(rows), 'excluded_missing_agent_username': unknown_agent_count,
            'definition': 'Failed criterion = recorded score below criterion maximum (excluding Not Reached). '
                          'Repeat = same dialer username + dialer + issue on >= N distinct completed reviews; '
                          'this does not by itself prove coaching or intent.',
            'warning': 'Shows current scorecard criterion maxima; historical scorecard versions may differ.'}


@register('find_repeat_critical_errors', 'Identify dialer agents with the SAME critical error on multiple authorized submitted reviews.',
          {**FILTERS, 'minimum_occurrences': I('Minimum reviews', 2, 20), 'limit': I('Maximum rows', 1, 40)})
def find_repeat_critical_errors(*, user, minimum_occurrences=2, limit=20, **kwargs):
    rows = _read_rows(_period(user, **kwargs).exclude(critical_errors=[]))
    counts, agents = defaultdict(list), {}
    for r in rows:
        key = _agent_key(r)
        if not key:
            continue
        agents[key] = _agent(r)
        for error in set(r.critical_errors or []):
            counts[(key, error)].append(r)
    matches = [{'agent': agents[agent], 'error_key': key, 'error_label': ERROR_LABELS.get(key, key),
                'occurrences': len(reviews), 'evidence': [_evidence(r) for r in reviews[:8]]}
               for (agent, key), reviews in counts.items() if len(reviews) >= minimum_occurrences]
    matches.sort(key=lambda v: -v['occurrences'])
    return {'matches': matches[:limit], 'match_count': len(matches)}


@register('get_criterion_failures', 'Rank QA scorecard subcriteria most often scored below their maximum on submitted reviews.',
          {**FILTERS, 'limit': I('Maximum criteria', 1, 40)})
def get_criterion_failures(*, user, limit=15, **kwargs):
    rows = _read_rows(_period(user, **kwargs))
    failed, applicable = Counter(), Counter()
    for r in rows:
        for key, score in (r.scores or {}).items():
            if key not in CRITERIA:
                continue
            _label, maximum, category, _c = CRITERIA[key]
            if (r.criterion_applicability or {}).get(key) == 'not_reached' or \
               (r.category_applicability or {}).get(category) == 'not_reached':
                continue
            try:
                below = Decimal(str(score)) < Decimal(str(maximum))
            except (ValueError, TypeError, InvalidOperation):
                continue
            applicable[key] += 1
            if below:
                failed[key] += 1
    return {'criteria': [{'key': key, 'label': CRITERIA[key][0], 'failed_reviews': n,
                          'scored_reviews': applicable[key],
                          'failure_rate_pct': round(100 * n / applicable[key], 1)}
                         for key, n in failed.most_common(limit)],
            'definition': 'A score below maximum is counted as below-max, not necessarily a zero/fail.'}


@register('get_coaching_backlog', 'Count QA reports in coaching-planned state or with overdue coaching due dates.',
          {**FILTERS, 'limit': I('Maximum reports', 1, 50)})
def get_coaching_backlog(*, user, limit=20, **kwargs):
    qs = _period(user, **kwargs).filter(leader_status=Review.LeaderStatus.COACHING_PLANNED)
    overdue = qs.filter(coaching_due_at__lt=timezone.now())
    return {'coaching_planned': qs.count(), 'overdue': overdue.count(),
            'reports': [{'review_id': str(r.pk), 'agent': _agent(r),
                         'coaching_due_at': r.coaching_due_at.isoformat() if r.coaching_due_at else None}
                        for r in overdue.order_by('coaching_due_at')[:limit]]}


@register('get_review_workflow_events', 'Recent workflow event types, dates, responsible actors for ONE authorized review. Excludes free-form notes.',
          {'review_id': S('Exact review UUID', 36), 'limit': I('Maximum events', 1, 30)}, ('review_id',))
def get_review_workflow_events(*, user, review_id, limit=15):
    review = permitted_reviews(user).filter(pk=_uuid(review_id, 'review_id')).first()
    if not review:
        return {'found': False}
    events = review.workflow_events.select_related('actor').order_by('-created_at')[:limit]
    return {'found': True, 'review_id': str(review.pk), 'events': [
        {'event_type': e.event_type, 'from_status': e.from_status, 'to_status': e.to_status,
         'actor_name': e.actor.full_name, 'created_at': e.created_at.isoformat()}
        for e in events]}
