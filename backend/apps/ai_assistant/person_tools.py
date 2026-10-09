"""Resolve organizational people solely through reports visible to this user.

A dialer agent is not a portal team leader. Never merge the two identities.
"""
from django.db.models import Q, Count
from difflib import SequenceMatcher
import re
from rest_framework.exceptions import ValidationError
from apps.access.policy import permitted_management_reviews
from apps.analytics.services.core import COMPLETE


def lookup_visible_people(*, user, search, role='any', limit=12):
    query = ' '.join(search.split()).strip()
    if len(query) < 2 or len(query) > 120:
        raise ValidationError({'search': 'Provide 2 to 120 characters.'})
    if role not in ('any', 'team_leader', 'agent'):
        raise ValidationError({'role': 'Unsupported person role.'})
    qs = permitted_management_reviews(user).filter(status__in=COMPLETE)
    matches = []
    if role in ('any', 'team_leader'):
        words = query.split()
        # Portal users authenticate by email and have no username model field.
        # Match supported User fields only; names are always scoped to visible reviews.
        leader_filter = Q(team_leader__email__icontains=query)
        if len(words) >= 2:
            leader_filter |= Q(team_leader__first_name__icontains=words[0],
                               team_leader__last_name__icontains=' '.join(words[1:]))
        else:
            leader_filter |= Q(team_leader__first_name__icontains=query) | Q(team_leader__last_name__icontains=query)
        leaders = (qs.exclude(team_leader__isnull=True).filter(leader_filter)
                   .values('team_leader_id', 'team_leader__first_name', 'team_leader__last_name')
                   .annotate(visible_evaluations=Count('pk')).order_by('-visible_evaluations')[:limit+1])
        for leader in leaders:
            matches.append({'role': 'team_leader', 'id': str(leader['team_leader_id']),
                            'name': ' '.join(filter(None, (leader['team_leader__first_name'],
                                                          leader['team_leader__last_name']))),
                            'visible_evaluations': leader['visible_evaluations']})
    if role in ('any', 'agent'):
        agents = (qs.filter(Q(call__agent_name__icontains=query) | Q(call__agent_user__icontains=query))
                  .values('call__dialer_id', 'call__agent_user', 'call__agent_name')
                  .annotate(visible_evaluations=Count('pk')).order_by('-visible_evaluations')[:limit+1])
        for agent in agents:
            matches.append({'role': 'agent', 'dialer_id': str(agent['call__dialer_id']),
                            'agent_user': agent['call__agent_user'],
                            'name': agent['call__agent_name'],
                            'visible_evaluations': agent['visible_evaluations']})
    # Only when direct matching fails: fuzzy match a bounded directory derived from
    # authorized completed evaluations. No global account enumeration.
    if not matches:
        def norm(value):
            return re.sub(r'[^a-z0-9]+', '', (value or '').casefold())
        term = norm(query)
        fuzzy = []
        if role in ('any', 'team_leader'):
            directory = list(qs.exclude(team_leader__isnull=True).values(
                'team_leader_id', 'team_leader__first_name', 'team_leader__last_name'
            ).annotate(visible_evaluations=Count('pk')).order_by('-visible_evaluations')[:201])
            if len(directory) <= 200:
                for row in directory:
                    full = ' '.join(filter(None, (row['team_leader__first_name'], row['team_leader__last_name'])))
                    ratio = SequenceMatcher(None, term, norm(full)).ratio()
                    if ratio >= 0.84:
                        fuzzy.append((ratio, {'role': 'team_leader', 'id': str(row['team_leader_id']),
                                              'name': full, 'visible_evaluations': row['visible_evaluations'],
                                              'match_type': 'approximate'}))
        if role in ('any', 'agent'):
            directory = list(qs.values('call__dialer_id', 'call__agent_user',
                                       'call__agent_name').annotate(visible_evaluations=Count('pk'))
                             .order_by('-visible_evaluations')[:201])
            if len(directory) <= 200:
                for row in directory:
                    label = row['call__agent_name'] or row['call__agent_user']
                    ratio = max(SequenceMatcher(None, term, norm(label)).ratio(),
                                SequenceMatcher(None, term, norm(row['call__agent_user'])).ratio())
                    if ratio >= 0.84:
                        fuzzy.append((ratio, {'role': 'agent', 'dialer_id': str(row['call__dialer_id']),
                                              'agent_user': row['call__agent_user'], 'name': label,
                                              'visible_evaluations': row['visible_evaluations'],
                                              'match_type': 'approximate'}))
        fuzzy.sort(key=lambda item: -item[0])
        matches = [row for _, row in fuzzy[:limit+1]]
    else:
        for row in matches:
            row['match_type'] = 'direct'
    return {'matches': matches[:limit], 'ambiguous': len(matches) > 1,
            'truncated': len(matches) > limit,
            'note': 'Matches restricted to authorized submitted evaluations; approximate spelling is explicitly identified and ambiguous names require clarification.'}
