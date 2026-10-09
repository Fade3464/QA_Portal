"""Pure, bounded analytical conversation state and deterministic ranked answers.

This state records *a query specification*, not historical QA tool output. Every
follow-up re-runs the authorized Django query to handle changed access/data.
"""
import re
from dataclasses import dataclass

RANK_METRICS = {'critical_error_reviews', 'average_score', 'evaluation_count'}
FILTER_KEYS = ('company_id', 'branch_id', 'team_id', 'project_name', 'agent_user', 'dialer_id')


@dataclass(frozen=True)
class RankFocus:
    position: int | None = None
    count: int = 1
    after: str = ''
    distinct: bool = True


def is_ranking_followup(text, previous):
    if not isinstance(previous, dict) or previous.get('last_analysis', {}).get('kind') != 'agent_ranking':
        return False
    q = text.strip().casefold()
    metric = previous['last_analysis'].get('metric')
    # Topic or metric changes start a new authorized investigation, not a stale
    # reuse of agent ranking from a previous turn.
    if re.search(r'\b(?:team leaders?|supervisors?|projects?|dialers?)\b', q):
        return False
    if metric != 'average_score' and re.search(r'\b(?:average score|scored|scoring|lowest score)\b', q):
        return False
    if metric != 'critical_error_reviews' and re.search(r'\b(?:critical errors?|critical violations?)\b', q):
        return False
    return bool(re.search(r'\b(?:next|other|others|rank|ranked|second|third|fourth|fifth|sixth|'
                          r'top|bottom|worst|best|following|after|who else|number\s+\d+|'
                          r'\d+(?:st|nd|rd|th))\b', q))


def is_context_followup(text, previous):
    if not isinstance(previous, dict) or not previous.get('last_analysis'):
        return False
    q = text.casefold()
    return (is_ranking_followup(text, previous) or
            bool(re.search(r'\b(?:his|her|their|same|that agent|that leader|and what|what about|how about|'
                           r'those|them|the violation|the critical call)\b', q)) or
            bool(re.search(r'\b(?:what|which)\b.{0,65}\b(?:violation|critical|mistake)\b', q)))


def rank_focus(question):
    q = question.casefold()
    after = ''
    m = re.search(r'\b(?:next\s+(?:to|after)|following|after)\s+([\w][\w\s-]{0,45}?)(?:\?|\.|$|,)', q)
    if m:
        after = m.group(1).strip().strip('"\' ')
    pos = None
    ordinals = {'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
                'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10}
    for word, number in ordinals.items():
        if re.search(r'\b' + word + r'\b', q):
            pos = number
            break
    match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)\b', q)
    if match:
        pos = int(match.group(1))
    match = re.search(r'\b(?:top|bottom|other|first|last)\s+(\d{1,2})\b', q)
    count = int(match.group(1)) if match else (10 if 'top ten' in q else 1)
    if 'other nine' in q or 'other 9' in q:
        count = 9
    # A list of "other N" after a top-N answer is not one more first place.
    return RankFocus(position=pos, count=min(25, max(1, count)), after=after)


def ranking_context(tool_output, *, period):
    if tool_output.get('name') != 'rank_agents':
        return None
    data, args = tool_output['data'], tool_output['arguments']
    metric = data.get('metric')
    if metric not in RANK_METRICS:
        return None
    filters = {k: args[k] for k in FILTER_KEYS if isinstance(args.get(k), str) and args[k]}
    return {'kind': 'agent_ranking', 'metric': metric,
            'order': data.get('order', 'worst'), 'filters': filters,
            'period': {'date_from': period.start.isoformat(), 'date_to': period.end.isoformat()}}


def _number(value):
    return f'{value:g}' if isinstance(value, float) else str(value)


def _metric_value(agent, metric):
    return agent.get('evaluations' if metric == 'evaluation_count' else metric)


def ranking_groups(data):
    """Competition-style rank groups; same score means same rank, not 2nd/3rd."""
    metric = data.get('metric')
    groups = []
    for row in data.get('agents', []):
        value = _metric_value(row, metric)
        if value is None:
            continue
        if groups and groups[-1]['value'] == value:
            groups[-1]['agents'].append(row)
        else:
            groups.append({'rank': 1 + sum(len(g['agents']) for g in groups),
                           'value': value, 'agents': [row]})
    return groups


def _agent_label(row):
    name = (row.get('agent_name') or row.get('agent_user') or 'Unknown agent').strip()
    login = row.get('agent_user') or ''
    return f'**{name}** ({login})' if name != login else f'**{name}**'


def describe_ranking(data, question='', *, previous=None):
    metric = data.get('metric')
    if metric not in RANK_METRICS:
        return None
    groups = ranking_groups(data)
    if not groups:
        return ('No eligible agents were found for this ranking in your authorized reports. '
                'Average-score rankings require at least three scored reviews per agent.'
                if metric == 'average_score' else 'No agents with relevant submitted evaluations were found in the selected period.')
    focus = rank_focus(question)
    q = question.casefold()
    plural_list = focus.count > 1 or 'summary' in q or 'list' in q or 'agents' in q and 'top' in q
    description = {'critical_error_reviews': 'evaluations containing an explicitly recorded critical error',
                   'average_score': 'average QA score',
                   'evaluation_count': 'completed QA evaluations'}[metric]
    lines = []
    if focus.after:
        group_index = next((i for i, group in enumerate(groups) if any(
            focus.after in (r.get('agent_name') or '').casefold() or
            focus.after == (r.get('agent_user') or '').casefold() for r in group['agents'])), None)
        if group_index is None:
            return (f'I could not find {focus.after!r} in the current authorized ranking. '
                    'Please specify the exact agent name or a ranking position.')
        current = groups[group_index]
        tied = ', '.join(_agent_label(r) for r in current['agents'])
        if len(current['agents']) > 1:
            lines.append(f'{tied} share rank {current["rank"]} with {_number(current["value"])} {description}.')
        if group_index+1 >= len(groups):
            lines.append('There is no lower distinct rank among the returned eligible agents.')
        else:
            g = groups[group_index+1]
            lines.append(f'Next distinct rank ({g["rank"]}): ' + ', '.join(_agent_label(r) for r in g['agents']) +
                         f' — {_number(g["value"])} {description}.')
    elif focus.position is not None:
        # "3rd worst" refers to 3rd distinct metric value. State the competition rank.
        distinct_index = focus.position - 1
        if distinct_index >= len(groups):
            return (f'There is no distinct #{focus.position} value among the returned eligible agents. '
                    f'Ties share their rank; {len(groups)} distinct value group(s) are available.')
        group = groups[distinct_index]
        lines.append(f'Distinct group #{focus.position} (competition rank {group["rank"]}): ' +
                     ', '.join(_agent_label(r) for r in group['agents']) +
                     f' — {_number(group["value"])} {description}.')
        if group['rank'] != focus.position:
            lines.append('Earlier ties account for the difference between group position and competition rank.')
    elif plural_list:
        requested = min(25, focus.count if focus.count > 1 else 10)
        if ('other' in q or 'remaining' in q) and isinstance(previous, dict):
            start = 1
        else:
            start = 0
        agents = [r for g in groups for r in g['agents']]
        if start >= len(agents):
            return 'No further eligible agents appear in the authorized ranking.'
        shown = 0
        lines.append(f'{description.capitalize()} — agent ranking (ties share the same metric value):')
        for g in groups:
            for row in g['agents']:
                index = agents.index(row)
                if index < start or shown >= requested:
                    continue
                lines.append(f'- Rank {g["rank"]}: {_agent_label(row)} — {_number(g["value"])}')
                shown += 1
        if len(agents) < start+requested:
            lines.append(f'Only {len(agents)} eligible agent(s) were returned for the requested scope.')
        if len(agents) >= 25:
            lines.append('The ranking is capped at 25 agents; other agents may exist.')
    else:
        g = groups[0]
        lines.append('Highest-ranked group: ' + ', '.join(_agent_label(r) for r in g['agents']) +
                     f' — {_number(g["value"])} {description}.')
        if len(g['agents']) > 1:
            lines.append(f'{len(g["agents"])} agents share first place; there is no unique worst agent.')
    if metric == 'critical_error_reviews':
        lines.append('This measures evaluations with critical errors, not the number of individual error events or all below-max QA criteria.')
    elif metric == 'average_score':
        lines.append('Only agents with at least three scored evaluations are ranked.')
    return '\n'.join(lines)
