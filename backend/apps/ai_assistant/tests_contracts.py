"""Pure request-contract regressions. No provider or database is mocked here;
these units have no provider/database dependencies (calendar uses Django clock).
"""
from copy import deepcopy
from datetime import date
import unittest
from .query_contract import plan_contract, QueryContract
from .social import social_response
from .timeframes import resolve_window
from .answer_contracts import render_backlog, render_team_ranking
from .conversation_analysis import is_ranking_followup

class RequestContractTests(unittest.TestCase):
    def prior(self, subject='agent', order='worst'):
        return {'query_contract': {'version': 1, 'subject': subject, 'operation': 'ranking',
                                  'metric': 'critical_error_reviews', 'order': order, 'filters': {}},
                'time_window': {'date_from': '2026-09-30', 'date_to': '2026-10-09'},
                'last_analysis': {'kind': subject+'_ranking', 'metric': 'critical_error_reviews', 'order': order, 'filters': {}}}

    def test_team_subject_overrides_wrong_model_and_agent_history(self):
        for direction in ('best', 'worst'):
            for phrase in ('which team has been performing', 'which teams performed', 'and which team is'):
                with self.subTest(direction=direction, phrase=phrase):
                    p = plan_contract(f'{phrase} the {direction} in the past 10 days',
                                      {'intent': 'agent_ranking', 'rank_metric': 'critical_error_reviews', 'order': 'worst'}, self.prior())
                    self.assertEqual((p.subject, p.operation, p.metric, p.order, p.primary_tool),
                                     ('team', 'ranking', 'average_score', direction, 'rank_teams'))
                    self.assertFalse(p.reuse)

    def test_person_backlog_cannot_answer_a_collection(self):
        p = plan_contract('Which team leaders have pending QA reports this week?',
                          {'intent': 'leader_backlog', 'entity_name': 'Asim Jamal'},
                          {'query_contract': {'version': 1, 'subject': 'team_leader', 'operation': 'backlog',
                                              'entity_name': 'Asim Jamal', 'filters': {'team_leader_id': 'id1'}}})
        self.assertTrue(p.collection)
        self.assertEqual(p.entity_name, '')
        self.assertFalse(p.matches('find_pending_reviews', {'team_leader_id': 'id1'}, {}))
        self.assertTrue(p.matches('find_pending_reviews', {}, {}))

    def test_subject_prefix_agents_in_my_team_stays_agents(self):
        p = plan_contract('Which agents in my team have the most violations?')
        self.assertEqual(p.subject, 'agent')
        self.assertEqual(p.metric, 'critical_error_reviews')

    def test_new_direction_overrides_prior(self):
        p = plan_contract('and which is best?', previous=self.prior(subject='team'))
        self.assertEqual((p.subject, p.order), ('team', 'best'))

    def test_legacy_followup_rejects_explicit_team(self):
        self.assertFalse(is_ranking_followup('which team is best', self.prior()))
        self.assertFalse(is_ranking_followup('which agent is best', self.prior()))

    def test_synonym_plan_is_validated_without_tool_keyword_requirement(self):
        p = plan_contract('Where is our QA quality weakest?',
                          {'subject': 'team', 'operation': 'ranking', 'order': 'worst', 'rank_metric': 'average_score'})
        self.assertEqual(p.primary_tool, 'rank_teams')

    def test_model_cannot_invent_named_person(self):
        p = plan_contract('Which leaders have outstanding reports?', {'entity_name': 'Asim Jamal'})
        self.assertFalse(p.entity_name)

    def test_entity_preserved_when_actually_named(self):
        p = plan_contract('How many reports are pending for Ahsan Tanveer?')
        self.assertEqual(p.entity_name, 'Ahsan Tanveer')
        self.assertFalse(p.collection)

    def test_named_leader_as_verb_subject_is_not_collective(self):
        for text, name in (
            ('How many reports has tl1 Test not reviewed?', 'tl1 Test'),
            ('How many reports has Ahsan Tanveer not reviewed this week?', 'Ahsan Tanveer'),
            ('How many reports have Asim Jamal not reviewed?', 'Asim Jamal'),
            ('How many reports has Ahsan Tanveer not yet reviewed?', 'Ahsan Tanveer'),
        ):
            with self.subTest(text=text):
                plan = plan_contract(text, {'intent': 'leader_backlog'})
                self.assertEqual(plan.entity_name, name)
                self.assertFalse(plan.collection)
                self.assertEqual(plan.primary_tool, 'find_pending_reviews')

    def test_generic_review_questions_do_not_invent_people(self):
        for text in (
            'How many reports have not been reviewed?',
            'How many reports have been reviewed?',
            'How many reports have all team leaders reviewed?',
            'Which team leaders have not reviewed reports?',
        ):
            with self.subTest(text=text):
                plan = plan_contract(text, {'intent': 'leader_backlog'})
                self.assertFalse(plan.entity_name)
                self.assertTrue(plan.collection)

    def test_query_contract_matches_direction_and_metric(self):
        p = plan_contract('which team performed best')
        needed = {'metric': 'average_score', 'order': 'best', 'date_from': '2026-10-01'}
        self.assertTrue(p.matches('rank_teams', needed, needed))
        self.assertFalse(p.matches('rank_agents', needed, needed))
        self.assertFalse(p.matches('rank_teams', {**needed, 'order': 'worst'}, needed))
        self.assertFalse(p.matches('rank_teams', {**needed, 'metric': 'critical_error_reviews'}, needed))
        self.assertFalse(p.matches('rank_teams', {**needed, 'team_id': 'surprise'}, needed))

    def test_age_filter_is_not_silently_added(self):
        p = plan_contract('which leaders have pending reports')
        self.assertFalse(p.matches('find_pending_reviews', {'older_than_days': 365}, {}))

    def test_model_authority_fields_never_in_contract(self):
        p = plan_contract('Which team performed worst?', {'role': 'admin', 'user_id': 1, 'is_superuser': True})
        self.assertNotIn('role', p.public())
        self.assertEqual(p.filters, {})

    def test_our_project_is_not_named_person(self):
        p = plan_contract('How many reports are pending for our project?')
        self.assertFalse(p.entity_name)

    def test_all_time_not_a_person(self):
        p = plan_contract('Which team leaders have pending QA reports for all time?')
        self.assertFalse(p.entity_name)
        self.assertTrue(p.collection)

    def test_new_collection_clears_scope_of_previous_person(self):
        prior = {'query_contract': {'version': 1, 'subject': 'team_leader', 'operation': 'backlog',
                                   'entity_name': 'Asim', 'filters': {'team_leader_id': 'abc'}}}
        for q in ('and which team leaders have pending reviews', 'all team leaders with pending reports'):
            self.assertNotIn('team_leader_id', plan_contract(q, previous=prior).filters)


class CalendarContractTests(unittest.TestCase):
    def test_all_time_has_no_sentinel_date(self):
        for text in ('for all time', 'all-time', 'entire history', 'since the beginning', 'ever'):
            with self.subTest(text=text):
                w = resolve_window(text, today=date(2026,10,9))
                self.assertTrue(w.all_time)
                self.assertIsNone(w.start)
                self.assertEqual(w.tool_args(), {'all_time': True})
                self.assertEqual(w.public()['label'], 'all time')

    def test_relative_period_wins_over_prior_all_time(self):
        prior = {'time_window': {'all_time': True}}
        w = resolve_window('and the best in past 10 days', today=date(2026,10,9), previous=prior)
        self.assertEqual((w.start, w.end), (date(2026,9,30), date(2026,10,9)))

    def test_all_time_followup_preserved(self):
        w = resolve_window('and how many critical?', previous={'time_window': {'all_time': True}})
        self.assertTrue(w.all_time)

    def test_yesterday_always_one_local_day(self):
        w = resolve_window('yesterday', today=date(2026,1,1))
        self.assertEqual((w.start,w.end), (date(2025,12,31),date(2025,12,31)))

    def test_two_weeks_inclusive(self):
        w = resolve_window('past 2 weeks', today=date(2026,10,9))
        self.assertEqual(w.days, 14)
        self.assertEqual(w.start, date(2026,9,26))

    def test_invalid_period_rejected(self):
        for q in ('past 0 days', 'past 400 days', 'past 99 weeks', '2026-10-09 to 2026-10-01'):
            with self.subTest(q=q), self.assertRaises(ValueError):
                resolve_window(q)


class SocialContractTests(unittest.TestCase):
    def test_common_personal_questions(self):
        questions = ['how are you?', 'are you avaialble?', 'Are you available?', 'are you there?',
                     'hello', 'hi there', 'how is it going?', "what's your name?", 'who are you?',
                     'are you human?', 'do you have feelings?', 'can you help me?', 'thank you',
                     'good evening', 'are you still online?', 'how are you doing?', 'bye',
                     'are you ready to help?', 'how old are you?', 'where do you live?']
        for q in questions:
            with self.subTest(q=q):
                self.assertIsInstance(social_response(q), str)

    def test_greeting_never_swallows_business_questions(self):
        for q in ('Hello, which team performed worst?', 'Are you available to check pending reviews?',
                  'How are you calculating scores?', 'Hi, which agents had violations?'):
            with self.subTest(q=q):
                self.assertIsNone(social_response(q))


class AnswerContractTests(unittest.TestCase):
    def teams(self, order):
        rows = [{'team_id':'a','name':'Team Alpha','evaluations':8,'scored':8,'average_score':95.0,'critical_error_reviews':1},
                {'team_id':'b','name':'Team Beta','evaluations':4,'scored':4,'average_score':65.0,'critical_error_reviews':3}]
        if order == 'worst':
            rows.reverse()
        return {'metric':'average_score','order':order,'teams':rows}

    def test_team_best_and_worst_use_correct_rows_and_language(self):
        best = render_team_ranking(self.teams('best'), 'which team is best')
        worst = render_team_ranking(self.teams('worst'), 'which team is worst')
        self.assertIn('**Team Alpha**', best)
        self.assertNotIn('**Team Beta**', best)
        self.assertIn('**Team Beta**', worst)
        self.assertNotIn('**Team Alpha**', worst)
        self.assertNotIn('agent', best)

    def test_team_tie_is_not_unique_winner(self):
        data = self.teams('best')
        data['teams'][1]['average_score'] = 95.0
        answer = render_team_ranking(data, 'best team')
        self.assertIn('tied', answer)
        self.assertIn('Team Alpha', answer)
        self.assertIn('Team Beta', answer)

    def test_team_minimum_sample_not_replaced_by_agent(self):
        self.assertIn('insufficient', render_team_ranking({'metric':'average_score','teams':[]}).lower())

    def test_all_time_backlog_has_no_30_day_claim(self):
        d = {'total_pending': 144,'submitted_in_period_pending':144,'period':{'all_time':True},
             'leaders':[{'name':'Ahsan','pending':75,'overdue':75},{'name':'Asim','pending':24,'overdue':16}]}
        text = render_backlog(d, {'all_time':True})
        self.assertIn('144', text)
        self.assertIn('Ahsan', text)
        self.assertIn('Asim', text)
        self.assertIn('no submission-date cutoff', text)
        self.assertNotIn('30', text)

    def test_every_returned_leader_not_only_last_lookup(self):
        d = {'total_pending': 15, 'submitted_in_period_pending': 15,
             'leaders':[{'name':f'TL {i}','pending':1,'overdue':0} for i in range(15)]}
        text = render_backlog(d, {})
        self.assertIn('TL 0', text)
        self.assertIn('TL 14', text)

    def test_zero_not_proof_everyone_reviewed(self):
        text = render_backlog({'total_pending':0,'leaders':[], 'period': {'all_time':True}}, {'all_time':True})
        self.assertIn('does not prove', text)
