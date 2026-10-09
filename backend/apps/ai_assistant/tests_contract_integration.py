"""Real Django ORM regressions; only the language-model transport is replaced.

These intentionally use the project's actual User/Review/Team models and shared
access policy. The offline harness is NOT a substitute for these tests.
"""
import json
from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from . import tests as fixtures
from .investigation import run_ai
from .provider import Completion
from .registry import invoke
from .models import AIConversation
from .access import scope_digest
from apps.calls.models import CallEvent, Review


def tool_call(name, args, ident='t'):
    return Completion(message={'tool_calls':[{'id':ident,'type':'function',
                     'function':{'name':name,'arguments':json.dumps(args)}}]}, finish_reason='tool_calls')


def chooser(names, **semantics):
    return tool_call('select_qa_tools', {'names':names, **semantics}, 'select')


class ContractFixtures:
    @classmethod
    def setUpTestData(cls):
        fixtures.AIAccessIntegrationTests.setUpTestData.__func__(cls)
        Review.objects.filter(pk__in=[r.pk for r in cls.reviews[:2]]).update(score=95)
        Review.objects.filter(pk=cls.reviews[2].pk).update(score=65)
        for i, team, campaign, score in [(20, cls.team1, 'CAMP-A',95),
                                          (21, cls.team2, 'CAMP-B',65), (22, cls.team2, 'CAMP-B',65)]:
            call = CallEvent.objects.create(dialer=cls.dialer, branch=cls.branch, team=team,
                campaign=campaign, event_key=f'contract-extra-{i}', event_type=CallEvent.EventType.DISPOSITION,
                agent_user=f'fixture-{i}', agent_name=f'Synthetic Agent {i}')
            Review.objects.create(call=call, reviewer=cls.qa, team_leader=team.team_leader,
                status=Review.Status.COMPLETED, completed_at=timezone.now()-timedelta(days=1),
                score=score, leader_status=Review.LeaderStatus.PENDING, critical_errors=['wasted_lead'])


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3')
class QueryContractORMTests(ContractFixtures, TestCase):
    def execute(self, question, replies, user=None, previous=None, **limits):
        p = Mock()
        p.complete.side_effect = replies
        conversation = AIConversation.objects.create(user=user or self.supervisor, scope_digest=scope_digest(user or self.supervisor), context_state=previous) if previous else None
        from contextlib import nullcontext
        with patch('apps.ai_assistant.investigation.get_provider', return_value=p), \
             (patch.multiple('apps.ai_assistant.investigation', **limits) if limits else nullcontext()):
            return run_ai(user or self.supervisor, question, conversation=conversation)

    def test_team_best_and_worst_are_true_team_aggregates(self):
        for order, expected in [('best',self.team1),('worst',self.team2)]:
            with self.subTest(order=order):
                d = invoke('rank_teams',self.supervisor,{'metric':'average_score','order':order})
                self.assertEqual(d['teams'][0]['team_id'],str(expected.pk))
                self.assertEqual(d['entity_type'],'team')
                self.assertEqual(d['total_eligible'],2)

    def test_model_agent_tool_cannot_answer_team_query(self):
        r=self.execute('Which team has been performing the worst in the past 10 days?',[
            chooser(['rank_agents'],intent='agent_ranking',rank_metric='critical_error_reviews'),
            tool_call('rank_agents',{'metric':'critical_error_reviews'}), Completion({'content':'Agent agent001 is worst'},'stop')])
        self.assertIn('Team Two',r['answer'])
        self.assertNotIn('Agent agent001',r['answer'])
        self.assertNotIn('rank_agents',r['tools_used'])
        self.assertEqual(r['interpretation']['subject'],'team')

    def test_worst_then_best_is_not_stale_ranking(self):
        first=self.execute('Which team performed worst in the past 10 days?',[
            chooser(['rank_teams']), tool_call('rank_teams',{'metric':'average_score','order':'worst'}), Completion({'content':'Summary'},'stop')])
        second=self.execute('and which team performed best?',[],previous=first['context_state'])
        self.assertIn('Team One',second['answer']); self.assertNotIn('Team Two',second['answer'])
        self.assertEqual(second['interpretation']['order'],'best')
        self.assertEqual(second['interpretation']['date_from'],first['interpretation']['date_from'])

    def test_pm_team_rankings_never_include_unassigned_project(self):
        d=invoke('rank_teams',self.pm,{'metric':'average_score','order':'worst','all_time':True})
        self.assertEqual([r['team_id'] for r in d['teams']],[str(self.team1.pk)])

    def test_team_score_ranking_minimum_sample_remains_enforced(self):
        Review.objects.filter(call__team=self.team2).update(score=None)
        d=invoke('rank_teams',self.supervisor,{'metric':'average_score','order':'worst'})
        self.assertEqual(len(d['teams']),1)
        self.assertEqual(d['teams'][0]['team_id'],str(self.team1.pk))

    def test_team_critical_metric_supported_without_agent_substitution(self):
        d=invoke('rank_teams',self.supervisor,{'metric':'critical_error_reviews','order':'worst'})
        self.assertTrue(all('team_id' in r and 'agent_user' not in r for r in d['teams']))

    def test_collective_primary_at_round_limit_is_full_scope(self):
        r=self.execute('Which team leaders have pending QA reports this week?',[
            chooser(['lookup_visible_people','find_pending_reviews']),
            tool_call('lookup_visible_people',{'search':'tl1 Test','role':'team_leader'})], MAX_ROUNDS=1)
        self.assertIn('tl1 Test',r['answer']); self.assertIn('tl2 Test',r['answer'])
        self.assertIn('**6**',r['answer'])
        self.assertEqual(r['interpretation']['result_status'],'complete')
        self.assertTrue(r['evidence'])
        self.assertNotIn('last_person',r['context_state'])

    def test_collective_question_rejects_model_leader_filter(self):
        r=self.execute('Which team leaders have pending reports?',[
            chooser(['lookup_visible_people','find_pending_reviews']),
            tool_call('lookup_visible_people',{'search':'tl1 Test'}),
            tool_call('find_pending_reviews',{'team_leader_id':str(self.tl1.pk)}),
            Completion({'content':'Only tl1'},'stop')])
        self.assertIn('tl2 Test',r['answer'])
        self.assertNotIn('team_leader_id',r['context_state']['query_contract']['filters'])

    def test_all_time_backlog_removes_date_cutoff(self):
        Review.objects.filter(pk=self.reviews[0].pk).update(completed_at=timezone.now()-timedelta(days=800))
        r=self.execute('Which team leaders have pending QA reports for all time?',[
            chooser(['find_pending_reviews']), tool_call('find_pending_reviews',{}),Completion({'content':'Wrong 30 day result'},'stop')])
        self.assertIn('**6**',r['answer'])
        self.assertTrue(r['interpretation']['all_time'])
        self.assertIsNone(r['interpretation']['date_from'])
        self.assertNotIn('30 day',r['answer'])

    def test_all_time_summary_includes_older_records_but_keeps_scope(self):
        Review.objects.filter(pk=self.reviews[0].pk).update(completed_at=timezone.now()-timedelta(days=800))
        default=invoke('get_qa_overview',self.pm,{})
        alltime=invoke('get_qa_overview',self.pm,{'all_time':True})
        self.assertEqual(default['metrics']['evaluations'],2)
        self.assertEqual(alltime['metrics']['evaluations'],3)
        self.assertIsNone(alltime['period']['date_from'])

    def test_contradictory_all_time_and_dates_rejected_by_registry(self):
        with self.assertRaises(ValidationError):
            invoke('get_qa_overview',self.pm,{'all_time':True,'date_from':'2026-10-01'})

    def test_pending_cohort_uses_same_age_filtered_queryset(self):
        data=invoke('find_pending_reviews',self.pm,{'older_than_days':10})
        self.assertEqual(data['total_pending'],0)
        self.assertEqual(data['submitted_in_period_pending'],0)
        self.assertEqual(data['carried_over'],0)

    def test_all_time_call_library_keeps_its_own_access_policy(self):
        d=invoke('get_call_library_overview',self.pm,{'all_time':True})
        self.assertEqual(d['calls_received'],3)
        self.assertTrue(d['period']['all_time'])
        self.assertEqual(invoke('get_call_library_overview',self.other_supervisor,{'all_time':True})['calls_received'],0)

    def test_model_cannot_add_role_parameter_to_primary(self):
        r=self.execute('Which team performed best?',[
            chooser(['rank_teams']),tool_call('rank_teams',{'metric':'average_score','role':'administrator'}),
            Completion({'content':'Invented summary'},'stop')],user=self.pm)
        self.assertIn('Team One',r['answer']); self.assertNotIn('Team Two',r['answer'])

    def test_smalltalk_preserves_context_without_model_or_query(self):
        prev={'query_contract':{'version':1,'subject':'team','operation':'ranking','metric':'average_score','order':'worst','filters':{}},
              'time_window':{'all_time':True}}
        conv=AIConversation(user=self.pm,context_state=prev)
        with patch('apps.ai_assistant.investigation.get_provider') as provider, patch('apps.ai_assistant.investigation.invoke') as query:
            r=run_ai(self.pm,'how are you?',conversation=conv)
        provider.assert_not_called(); query.assert_not_called()
        self.assertEqual(r['context_state'],prev)
        self.assertFalse(r['evidence']); self.assertEqual(r['interpretation']['response_kind'],'conversation')

    def test_missing_primary_at_timeout_does_not_present_secondary_as_answer(self):
        r=self.execute('Which team performed best?',[chooser(['rank_teams'])],MAX_SECONDS=0)
        self.assertEqual(r['interpretation']['result_status'],'incomplete')
        self.assertFalse(r['evidence'])

    def test_next_team_rank_after_social_stays_same_analysis(self):
        first=self.execute('Which team performed best?',[
            chooser(['rank_teams']),tool_call('rank_teams',{'metric':'average_score','order':'best'}),Completion({'content':'done'},'stop')])
        social=self.execute('Are you available?',[],previous=first['context_state'])
        next_result=self.execute("and who's next?",[],previous=social['context_state'])
        self.assertIn('Team Two',next_result['answer'])
        self.assertNotIn('Team One',next_result['answer'])
        self.assertEqual(next_result['interpretation']['subject'],'team')

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_scope_revocation_during_inference_blocks_response_and_history(self):
        from django.urls import reverse
        from apps.tenancy.models import QAProjectAssignment
        conv=AIConversation.objects.create(user=self.pm,scope_digest=scope_digest(self.pm),context_state={})
        self.client.force_login(self.pm)
        def changed(*args, **kwargs):
            QAProjectAssignment.objects.filter(qa=self.pm).delete()
            return {'answer':'Sensitive earlier QA analysis','evidence':[],'tools_used':[]}
        with patch('apps.ai_assistant.views.v3_run_ai',side_effect=changed):
            r=self.client.post(reverse('ai-chat'),data=json.dumps({'message':'Analyze reports','conversation_id':str(conv.pk)}),content_type='application/json')
        self.assertEqual(r.status_code,409)
        self.assertNotIn('Sensitive',r.content.decode())
        self.assertEqual(conv.messages.count(),0)

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_smalltalk_saved_without_destroying_analytical_context(self):
        from django.urls import reverse
        prior={'time_window':{'all_time':True},'query_contract':{'version':1,'subject':'team','operation':'ranking','metric':'average_score','order':'best','filters':{}}}
        conv=AIConversation.objects.create(user=self.pm,scope_digest=scope_digest(self.pm),context_state=prior)
        self.client.force_login(self.pm)
        r=self.client.post(reverse('ai-chat'),data=json.dumps({'message':'Are you avaialble?','conversation_id':str(conv.pk)}),content_type='application/json')
        self.assertEqual(r.status_code,200)
        conv.refresh_from_db()
        self.assertEqual(conv.context_state,prior)
        self.assertEqual(conv.messages.count(),2)

    def test_semantic_personal_topic_does_not_query_qa(self):
        with patch('apps.ai_assistant.investigation.invoke') as domain:
            r=self.execute('Does software like you ever need a break?',[
                chooser([], request_kind='conversation', social_topic='personal')])
        domain.assert_not_called()
        self.assertEqual(r['interpretation']['response_kind'],'conversation')
        self.assertFalse(r['evidence'])
