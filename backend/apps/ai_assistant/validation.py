"""Deterministic answer validation/rendering for operational QA metrics.

An LLM chooses intent and may explain policies, but numerical management
assertions are rendered from authorized Django aggregates instead of generated
as unconstrained prose. For unknown or incomplete results, fail closed.
"""


def render_backlog(data):
    """Current pending != 'everybody reviewed'; explicitly communicate cohort meaning."""
    count = data['total_pending']
    interval = data['period']
    if data['interpretation'] == 'current_backlog':
        lead = f'{count} QA evaluation(s) currently await team-leader review in your accessible scope.'
        lead += (f" Of these, {data['submitted_in_period_pending']} were submitted between "
                 f"{interval['date_from']} and {interval['date_to']}; "
                 f"{data['carried_over']} were submitted outside that interval.")
    else:
        lead = (f"{count} QA evaluation(s) submitted between {interval['date_from']} "
                f"and {interval['date_to']} are still awaiting team-leader review in your accessible scope.")
    if count == 0:
        return lead + ' This does not establish that every report was reviewed; other states or inaccessible reports may exist.'
    rows = [f"{leader['name']}: {leader['pending']} pending ({leader['overdue']} older than 48 hours)."
            for leader in data['leaders'][:10]]
    if len(data['leaders']) > 10 or data['completeness']['leader_breakdown_truncated']:
        rows.append('Additional team leaders omitted from this display; the total remains complete.')
    return lead + '\n' + '\n'.join(rows)


def render_analytics(plan, outputs):
    """Render factually consequential answers without free-form generated statistics.

    Returns None only for tasks with no suitable structured result shape (e.g.
    explaining the scorecard policy). Caller may use carefully bounded LLM prose.
    """
    if not outputs:
        return 'There are no verified QA results to report.'
    by_name = {item['tool']: item['data'] for item in outputs}
    scope_note = 'These figures cover only QA records visible to your account.'
    name = plan.intent
    if name == 'review_backlog':
        return render_backlog(by_name['find_pending_reviews'])
    if name == 'recurring_mistakes':
        data = by_name['find_repeated_mistakes']
        groups = data.get('repeated_issues', [])
        if not groups:
            overview = by_name.get('get_qa_overview',{}).get('metrics',{})
            counted = overview.get('evaluations', data.get('evaluations_examined',0))
            return (f'No repeated issues met the selected threshold in {counted} accessible completed evaluations '
                    f'during this period. That does not rule out mistakes outside the selected timeframe. {scope_note}')
        rows = [f"{g['agent']['agent_name']} ({g['agent']['agent_user']}): "
                f"{g['mistake_label']} — {g['occurrences']} evaluations."
                for g in groups[:12]]
        extra = max(0, data.get('matched_groups',len(groups))-len(rows))
        if extra:
            rows.append(f'{extra} additional issue groups are not displayed. Narrow the filters to inspect them.')
        return (f"Found {data.get('matched_groups',len(groups))} recurring QA issue group(s) "
                f"among {data.get('evaluations_examined',0)} completed evaluations.\n"+
                '\n'.join(rows)+'\n'+scope_note)
    if name == 'critical_errors':
        data = by_name['get_critical_error_summary']
        errors = data.get('critical_errors',[])
        if not errors:
            return 'No explicit critical errors were found among accessible evaluations in this period. '+scope_note
        return ('Critical errors found in '+str(data.get('reviews_with_critical_errors',0))+
                ' reviewed evaluations:\n'+'\n'.join(f"{e['label']}: {e['review_count']} evaluation(s)." for e in errors[:15])+'\n'+scope_note)
    if name in ('qa_overview','agent_performance','project_performance'):
        tool = {'qa_overview':'get_qa_overview','agent_performance':'get_agent_performance',
                'project_performance':'get_project_performance'}[name]
        stats = by_name[tool].get('metrics',{})
        if stats.get('evaluations',0) == 0:
            return 'No completed QA evaluations matched the selected accessible scope and period. '+scope_note
        score = stats.get('average_score')
        return (f"Found {stats.get('evaluations')} completed QA evaluations, with average QA score "
                f"{'unavailable' if score is None else str(score)}; "
                f"{stats.get('critical_error_reviews',0)} evaluations include explicit critical errors, "
                f"and {stats.get('partial_calls',0)} are partial calls. {scope_note}")
    if name == 'review_compliance':
        leaders = by_name['get_team_leader_review_summary'].get('leaders',[])
        if not leaders:
            return 'No submitted evaluations were found for the requested period within your authorized scope. '+scope_note
        return ('Leader review-status summary (for evaluations completed in the selected period):\n'+
                '\n'.join(f"{l['name']}: {l['pending']} pending; {l['reviewed_or_progressed']} acknowledged or progressed."
                          for l in leaders[:15])+'\n'+scope_note)
    if name == 'team_ranking':
        data = by_name['rank_teams']
        teams = data.get('teams',[])
        if not teams:
            return 'No teams met the minimum sample requirement in the selected period. '+scope_note
        return ('Team results (small samples may not appear):\n'+
                '\n'.join(f"{t['name']}: {t['evaluations']} evaluations; mean score {t['average_score']}."
                          for t in teams[:12])+'\n'+scope_note)
    if name == 'performance_change':
        data = by_name['compare_periods']
        previous = data['previous_period']
        current = data['current_period']
        delta = data.get('score_delta_points')
        if delta is None:
            return 'Comparable average scores were unavailable across the two periods. '+scope_note
        return (f"The average score changed by {delta:+.2f} points, from "
                f"{previous['average_score']} ({previous['evaluations']} evaluations) to "
                f"{current['average_score']} ({current['evaluations']} evaluations). "
                'This is a measured change, not evidence of its cause. '+scope_note)
    if name == 'coaching_backlog':
        data = by_name['get_coaching_backlog']
        return (f"{data.get('coaching_planned',0)} submitted evaluations are in coaching-planned status; "
                f"{data.get('overdue',0)} have overdue coaching due dates. "
                'This does not prove coaching did or did not occur. '+scope_note)
    if name == 'performance_trend':
        data = by_name['get_score_trend'].get('daily',[])
        overview = by_name['get_qa_overview'].get('metrics',{})
        if not data:
            return 'No completed QA score trend is available for this period. '+scope_note
        return (f"Across {overview.get('evaluations',0)} submitted evaluations, the mean QA score was "
                f"{overview.get('average_score')}. Daily reporting covers {data[0]['date']} "
                f"through {data[-1]['date']} ({len(data)} days with evaluations). "+scope_note)
    if name == 'review_details':
        review = by_name['get_review_details']
        if not review.get('found'):
            return 'This QA evaluation was not found within your current permissions.'
        return (f"Review {review['review_id']}: status {review['status']}, TL status {review['leader_status']}; "
                f"score {review['score']}; {len(review.get('critical_errors',[]))} recorded critical error(s). "+scope_note)
    return None
