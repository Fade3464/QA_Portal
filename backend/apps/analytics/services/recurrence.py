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


def get_agent_critical_violations(*, user, search, date_from=None, date_to=None,
                                  company_id=None, branch_id=None, team_id=None,
                                  project_name=None, dialer_id=None, limit=12):
    """Return explicit violation categories for one stable, authorized agent identity.

    A Review has default ordering by assigned_at. Using values().distinct()
    without clearing that ordering makes two reports from the *same* agent
    appear to be different identities on PostgreSQL. Resolve by (dialer,
    normalized username), never by individual review or mutable display name.
    """
    term = (search or '').strip()
    if len(term) < 2:
        raise ValidationError({'search': 'Supply the exact agent username or display name.'})
    base = _period(user, date_from=date_from, date_to=date_to,
                   company_id=company_id, branch_id=branch_id, team_id=team_id,
                   project_name=project_name, dialer_id=dialer_id)
    matches = base.filter(Q(call__agent_name__iexact=term) |
                          Q(call__agent_user__iexact=term))

    # Clear Review.Meta.ordering before DISTINCT, and inspect enough rows to
    # detect ambiguity rather than mistakenly selecting the first candidate.
    candidate_rows = list(matches.order_by().values(
        'call__dialer_id', 'call__agent_user').distinct()[:101])
    if len(candidate_rows) > 100:
        return {'ambiguous': True, 'candidates': [],
                'note': 'Too many matching authorized agent identities; qualify by dialer and username.'}

    # Case-only differences in a dialer login are not new agents. A missing
    # login is NOT an identity: never merge unrelated calls by display name.
    identities = {}
    unknown_identity = False
    for row in candidate_rows:
        username = (row['call__agent_user'] or '').strip()
        if not username:
            unknown_identity = True
            continue
        key = (str(row['call__dialer_id']), username.casefold())
        identities.setdefault(key, {'dialer_id': str(row['call__dialer_id']),
                                    'agent_user': username})

    if unknown_identity:
        return {'ambiguous': True, 'candidates': list(identities.values())[:10],
                'note': 'One or more matching reports have no stable agent username; qualify by dialer and username or review ID.'}
    if len(identities) > 1:
        return {'ambiguous': True, 'candidates': list(identities.values())[:10],
                'note': 'More than one authorized dialer agent matches. Specify the exact dialer and username.'}
    if not identities:
        return {'found': False, 'note': 'No exact agent identity with visible submitted QA reports matches that name.'}

    identity = next(iter(identities.values()))
    reviews = _read_rows(base.filter(
        call__dialer_id=identity['dialer_id'],
        call__agent_user__iexact=identity['agent_user']))
    if not reviews:
        return {'found': False, 'note': 'No matching submitted evaluations remain in the authorized scope.'}
    critical_reviews = [r for r in reviews if r.critical_errors]
    counts = Counter(key for r in critical_reviews for key in set(r.critical_errors or []))
    # The current display name is illustrative only; the dialer+username is
    # the canonical identity even if the name changed across evaluations.
    return {'found': True,
            'agent': {'agent_name': reviews[0].call.agent_name or identity['agent_user'],
                      'agent_user': identity['agent_user'],
                      'dialer_id': identity['dialer_id']},
            'evaluations': len(reviews), 'critical_error_reviews': len(critical_reviews),
            'violations': [{'key': key, 'label': ERROR_LABELS.get(key, key), 'reviews': n}
                           for key, n in counts.most_common()],
            'reports': [{'review_id': str(r.pk),
                         'recorded_violations': [ERROR_LABELS.get(k, k) for k in r.critical_errors],
                         'completed_at': r.completed_at.isoformat() if r.completed_at else None}
                        for r in critical_reviews[:limit]],
            'detail_truncated': len(critical_reviews) > limit,
            'definition': 'Explicitly recorded critical errors by distinct evaluation; not inferred from score deficits.'}
