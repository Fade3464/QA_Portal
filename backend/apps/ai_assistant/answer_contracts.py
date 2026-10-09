"""Render primary factual results, never a convenient but unrelated tool result.

Model narratives cannot turn an individual into a collection, a team into an
agent, or an error count into a score. This is shared by success, refusal and
execution-limit finalization. It does not claim to prove free-form causality.
"""
from .conversation_analysis import describe_ranking, rank_focus

METRIC_LABELS = {'average_score': 'average QA score',
                 'critical_error_reviews': 'evaluations with recorded critical errors',
                 'evaluation_count': 'completed QA evaluations'}


def render_team_ranking(data, question=''):
    metric = data.get('metric')
    if metric not in METRIC_LABELS:
        return None
    rows = data.get('teams', [])
    if not rows:
        return ('No eligible teams have at least three scored QA evaluations in this reporting period. '
                'There is insufficient scored evidence to rank teams; I did not substitute agent rankings.'
                if metric == 'average_score' else
                'No eligible teams were found in the authorized QA records for this period.')
    field = 'evaluations' if metric == 'evaluation_count' else metric
    groups = []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        if groups and groups[-1]['value'] == value:
            groups[-1]['rows'].append(row)
        else:
            groups.append({'value': value, 'rank': sum(len(g['rows']) for g in groups)+1, 'rows': [row]})
    if not groups:
        return 'The requested team metric is unavailable for the matching evaluations.'
    focus = rank_focus(question)
    order = data.get('order', 'worst')
    adjective = 'Best' if order == 'best' else 'Worst'
    if focus.position:
        if focus.position > len(groups):
            return f'There is no distinct group #{focus.position} in the returned team ranking; tied values share a rank.'
        selected = [groups[focus.position-1]]
    elif focus.count > 1 or 'summary' in question.casefold() or 'list' in question.casefold():
        selected = groups
    else:
        selected = groups[:1]
    label = METRIC_LABELS[metric]
    lines = [f'{adjective}-ranked teams by **{label}** (ties share competition rank):']
    shown, maximum = 0, (focus.count if focus.count > 1 else 25 if len(selected) == 1 else 10)
    for group in selected:
        for row in group['rows']:
            if shown >= maximum:
                break
            value = group['value']
            lines.append(f"- Rank {group['rank']}: **{row['name']}** - {value} {label}; "
                         f"{row.get('evaluations', 0)} evaluations, {row.get('scored', 0)} scored.")
            shown += 1
    if len(selected) == 1 and len(selected[0]['rows']) > 1:
        lines.append('These teams are tied; there is no single ' + ('best' if order == 'best' else 'worst') + ' team on this metric.')
    if metric == 'average_score':
        lines.append('Ranking uses QA scores only, with at least three scored reviews per team. It is not an overall judgment of the team.')
    elif metric == 'critical_error_reviews':
        lines.append('This counts reviews with any recorded critical error, not individual violations or a severity score. Volumes differ across teams.')
    else:
        lines.append('Review volume is not a measure of work quality.')
    if data.get('completeness', {}).get('detail_truncated'):
        lines.append('Only the first 25 eligible teams are shown; a tie at the cutoff may continue beyond this list.')
    return '\n'.join(lines)


def render_backlog(data, args, *, contract=None):
    total = data['total_pending']
    mode = data.get('interpretation', args.get('mode', 'current_backlog'))
    all_time = bool(data.get('period', {}).get('all_time') or args.get('all_time'))
    leaders = data.get('leaders', [])
    person_id = args.get('team_leader_id')
    if person_id:
        leader = next((x for x in leaders if x.get('team_leader_id') == person_id), None)
        label = leader['name'] if leader else (contract.entity_name if contract and contract.entity_name else 'The selected team leader')
        first = f'**{label}** has {total} pending QA reports'
    else:
        first = f'**{total}** QA evaluations await team-leader review in your authorized scope'
    first += (' from the requested submission period.' if mode == 'submitted_in_period' else ' currently, including older outstanding reports.')
    lines = [first]
    if all_time:
        lines.append('All-time scope: no submission-date cutoff was applied. This is the current backlog, not a historical snapshot.')
    else:
        period = data.get('period', {})
        if period.get('date_from'):
            lines.append(f"{data['submitted_in_period_pending']} pending reports were submitted from {period['date_from']} to {period['date_to']}.")
        if data.get('carried_over'):
            lines.append(f"{data['carried_over']} were submitted before that period.")
        if data.get('submitted_after_period_pending'):
            lines.append(f"{data['submitted_after_period_pending']} were submitted after that period.")
    if not person_id:
        for row in leaders:
            suffix = '' if all_time else f"; {row.get('submitted_in_period', 0)} submitted in the reporting period"
            lines.append(f"- **{row['name']}**: {row['pending']} pending; {row['overdue']} older than 48 hours{suffix}.")
    elif leaders:
        lines.append(f"{data.get('overdue_48h', 0)} are older than 48 hours.")
    if data.get('missing_submission_date'):
        lines.append(f"{data['missing_submission_date']} pending reports have no submission timestamp.")
    if total == 0:
        lines.append('No matching accessible submitted reports are pending; this does not prove all review obligations were completed.')
    if data.get('completeness', {}).get('leader_breakdown_truncated'):
        lines.append('The leader breakdown is truncated; the total is the full authorized aggregate.')
    return '\n'.join(lines)


def render_primary(result, contract, question='', previous=None):
    name, data, args = result['name'], result['data'], result['arguments']
    if name == 'find_pending_reviews':
        return render_backlog(data, args, contract=contract)
    if name == 'rank_teams':
        return render_team_ranking(data, question)
    if name == 'rank_agents':
        return describe_ranking(data, question, previous=previous)
    if name == 'get_qa_overview':
        m = data['metrics']
        return (f"**{m['evaluations']}** completed QA evaluations match the requested scope and reporting period. "
                f"{m['critical_error_reviews']} evaluations contain at least one explicitly recorded critical error.")
    if name == 'get_call_library_overview':
        return (f"**{data['calls_received']}** Call Library records were received in the requested scope and reporting period. "
                'This includes calls without a completed QA evaluation.')
    if name == 'get_critical_error_summary':
        return f"**{data['reviews_with_critical_errors']}** evaluations contain explicitly recorded critical errors in the requested scope and period."
    return None


def validate_result_shape(name, data):
    """Malformed results are tool errors, not zero/no-eligible-agent evidence."""
    if not isinstance(data, dict):
        raise ValueError('Analytics returned an invalid response object.')
    if name in {'rank_agents', 'rank_teams'}:
        field = 'agents' if name == 'rank_agents' else 'teams'
        if data.get('metric') not in METRIC_LABELS or data.get('order') not in {'best', 'worst'} or not isinstance(data.get(field), list):
            raise ValueError('Ranking response lacks the required metric/direction/entity collection.')
        for row in data[field]:
            if not isinstance(row, dict):
                raise ValueError('Invalid ranking row.')
            required = ('agent_user', 'dialer_id') if field == 'agents' else ('team_id', 'name')
            if any(not row.get(key) for key in required):
                raise ValueError('Ranking row lacks a stable identity.')
    if name == 'find_pending_reviews':
        for key in ('total_pending', 'submitted_in_period_pending'):
            if type(data.get(key)) is not int or data[key] < 0:
                raise ValueError('Invalid pending-review aggregate.')
        if not isinstance(data.get('leaders'), list):
            raise ValueError('Pending-review result has no leader breakdown.')
    if name == 'get_qa_overview':
        if not isinstance(data.get('metrics'), dict) or type(data['metrics'].get('evaluations')) is not int:
            raise ValueError('Invalid QA summary.')
