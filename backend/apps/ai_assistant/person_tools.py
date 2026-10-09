"""Resolve organizational people solely through reports visible to this user.

A dialer agent is not a portal team leader. Never merge the two identities.
"""
from django.db.models import Q, Count
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
        leader_filter = Q(team_leader__username__icontains=query)
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
    return {'matches': matches[:limit], 'ambiguous': len(matches) > 1,
            'truncated': len(matches) > limit,
            'note': 'Matches are restricted to authorized submitted QA evaluations; the same name may identify different roles.'}
