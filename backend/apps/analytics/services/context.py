"""Bounded, permission-scoped QA context for the AI investigation engine.

Never deliver raw customer details, recordings, free-form call notes, or credentials
through model tools. Qualitative guidance is explicitly marked as QA reviewer input,
not an independent finding by the language model.
"""
import re
from difflib import SequenceMatcher
from django.db.models import Count
from django.conf import settings
from rest_framework.exceptions import ValidationError
from apps.access.policy import permitted_management_reviews
from apps.calls.scorecard import SCORECARD, CRITICAL_ERRORS
from .core import _base, _period, _dates, _uuid, _number, ERROR_LABELS, COMPLETE


def _normalize(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').casefold())


def _safe_text(value, size=360):
    """Limit accidental identifier/PII egress in optional QA narrative context."""
    value = str(value or '')[:2500]
    value = re.sub(r'\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b', '[email redacted]', value)
    value = re.sub(r'https?://\S+', '[link redacted]', value, flags=re.I)
    value = re.sub(r'(?<!\w)(?:\+?\d[\d().\s-]{8,}\d)(?!\w)', '[number redacted]', value)
    return re.sub(r'\s+', ' ', value).strip()[:size]


def list_visible_dialers(*, user, search='', date_from=None, date_to=None, limit=20, all_time=False):
    """Dialers are distinct from projects. Search only dialers represented by visible QA reviews."""
    rows = list(_base(user, date_from=date_from, date_to=date_to, all_time=all_time)
                .values('call__dialer_id', 'call__dialer__name')
                .annotate(evaluations=Count('pk')).order_by('-evaluations')[:201])
    if len(rows) > 200:
        raise ValidationError({'scope': 'Too many dialers to resolve safely.'})
    term = _normalize(search)
    variants = [term]
    if term.endswith('dialer') and len(term) > len('dialer') + 2:
        variants.append(term[:-6])  # 'ArenaMedicare dialer' names the ArenaMedicare dialer.
    candidates = []
    for row in rows:
        name = row['call__dialer__name']
        exact = bool(term and any(v == _normalize(name) for v in variants))
        similar = bool(term and max(SequenceMatcher(None, v, _normalize(name)).ratio() for v in variants) >= 0.84)
        if not term or exact or similar or any(v in _normalize(name) for v in variants if v):
            candidates.append({'dialer_id': str(row['call__dialer_id']), 'name': name,
                               'evaluations': row['evaluations'],
                               'match': 'exact' if exact else ('approximate' if similar and term != _normalize(name) else 'name')})
    return {'dialers': candidates[:limit], 'matched': len(candidates),
            'ambiguous': bool(term and len(candidates) > 1),
            'definition': 'Submitted/completed QA evaluations on visible dialers in the selected period, not the raw call-library total.',
            'note': 'A dialer name is not a project name. Confirm ambiguous or approximate matches.'}


def get_call_library_overview(*, user, date_from=None, date_to=None, dialer_id=None, all_time=False):
    """Counts raw CallEvent entries using the very same call-library permission scope."""
    from apps.calls.views import scoped_calls
    permitted_management_reviews(user)  # Explicit AI management-role gate.
    start, end = (None, None) if all_time else _dates(date_from, date_to)
    qs = scoped_calls(user)
    if not all_time:
        qs = qs.filter(received_at__date__gte=start, received_at__date__lte=end)
    if dialer_id:
        qs = qs.filter(dialer_id=_uuid(dialer_id, 'dialer_id'))
    return {'calls_received': qs.count(),
            'period': {'date_from': start.isoformat() if start else None, 'date_to': end.isoformat() if end else None, 'all_time': all_time},
            'definition': 'Call-library entries received_at in selected period. Includes unreviewed calls; not the number of QA evaluations.',
            'scope': 'Current user call-library permissions apply.'}


def get_review_qa_context(*, user, review_id):
    """Structured scores, heading/subheading applicability and sanitized reviewer feedback for ONE report."""
    review = permitted_management_reviews(user).filter(status__in=COMPLETE, pk=_uuid(review_id, 'review_id')).first()
    if not review:
        return {'found': False}
    # Prefer the immutable rubric snapshot saved with this particular review. A
    # historical review must not silently inherit today's headings/point maxima.
    snapshot = review.scorecard_snapshot if isinstance(review.scorecard_snapshot, dict) else {}
    captured = snapshot.get('categories')
    source = captured if isinstance(captured, list) and captured else [
        {'key': group['key'], 'label': group['label'], 'criteria': [
            {'key': k, 'label': label, 'max_score': maximum}
            for k, label, maximum in group['criteria']]} for group in SCORECARD]
    categories = []
    for group in source[:12]:
        if not isinstance(group, dict) or not isinstance(group.get('criteria'), list):
            continue
        criteria = []
        for criterion in group['criteria'][:60]:
            if not isinstance(criterion, dict):
                continue
            key = criterion.get('key')
            if key in (review.scores or {}) or key in (review.criterion_applicability or {}):
                criteria.append({'key': key, 'label': str(criterion.get('label') or key)[:120],
                                 'max_points': criterion.get('max_score'),
                                 'scored_points': (review.scores or {}).get(key),
                                 'applicability': (review.criterion_applicability or {}).get(key, 'applicable')})
        group_key = group.get('key')
        if criteria or group_key in (review.category_applicability or {}):
            categories.append({'heading': str(group.get('label') or group_key)[:120], 'key': group_key,
                               'applicability': (review.category_applicability or {}).get(group_key, 'applicable'),
                               'subheadings': criteria})
    if settings.AI_SEND_REVIEW_FEEDBACK:
        advice = {k: _safe_text(getattr(review, k)) for k in (
            'feedback_summary', 'strengths', 'improvement_areas', 'expected_behavior', 'coaching_plan')}
    else:
        advice = {'disabled': 'Reviewer free-text omitted until AI_SEND_REVIEW_FEEDBACK is enabled on encrypted inference transport.'}
    return {'found': True, 'review_id': str(review.pk), 'score': _number(review.score),
            'scorecard_version': review.scorecard_version,
            'rubric_source': 'review_snapshot' if captured else 'current_policy_fallback',
            'headings': categories,
            'critical_errors': [ERROR_LABELS.get(k, k) for k in (review.critical_errors or [])],
            'reviewer_feedback': advice,
            'provenance': 'Feedback and suggestions were written by a QA reviewer; not independently verified by AI.',
            'privacy': 'Customer identifiers, recordings, raw transcript, internal notes and criterion evidence excluded. Some identifiers in reviewer feedback are redacted.'}


def get_qa_feedback_examples(*, user, date_from=None, date_to=None, company_id=None,
                             branch_id=None, team_id=None, project_name=None,
                             agent_user=None, dialer_id=None, limit=5, all_time=False):
    """Small, auditable sample of reviewer-supplied improvement guidance; not a trend statistic."""
    qs = _period(user, date_from=date_from, date_to=date_to, company_id=company_id,
                 branch_id=branch_id, team_id=team_id, project_name=project_name,
                 agent_user=agent_user, dialer_id=dialer_id, all_time=all_time)
    if not settings.AI_SEND_REVIEW_FEEDBACK:
        return {'examples': [], 'sample_only': True, 'disabled': 'Qualitative feedback context is disabled until encrypted model transport is configured.'}
    rows = (qs.exclude(improvement_areas='', expected_behavior='', coaching_plan='').order_by('-completed_at', '-pk')[:limit])
    return {'examples': [{'review_id': str(row.pk),
                          'agent_name': row.call.agent_name or row.call.agent_user,
                          'improvement_areas': _safe_text(row.improvement_areas),
                          'expected_behavior': _safe_text(row.expected_behavior),
                          'coaching_plan': _safe_text(row.coaching_plan)} for row in rows],
            'sample_only': True,
            'provenance': 'Reviewer-written suggestions sampled from accessible completed QA evaluations. Do not generalize frequency or causes from this sample.'}
