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
