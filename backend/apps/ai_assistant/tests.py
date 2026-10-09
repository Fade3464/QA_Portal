"""Django integration tests: permissions, real report scope, tool validation, chat API.
Run with `python manage.py test apps.ai_assistant` in the backend container.
"""
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.calls.models import CallEvent, Review
from apps.tenancy.models import Branch, Company, Dialer, DialerCampaign, QAProjectAssignment, Team
from .access import permitted_reviews, scope_digest
from .models import AIConversation, AIMessage
from .provider import AIProviderError, OpenAICompatibleProvider
from .registry import invoke
from .orchestrator import selected_definitions


class ToolRoutingTests(SimpleTestCase):
    def test_mistake_tools_are_available(self):
        tools = selected_definitions('Who repeated a critical mistake again?')
        self.assertIn('find_repeated_mistakes', [t['function']['name'] for t in tools])
        self.assertLessEqual(len(tools), 9)

    @override_settings(AI_LLM_BASE_URL='http://public.example.com/v1', AI_LLM_ALLOW_HTTP=False)
    def test_http_requires_explicit_private_transport_configuration(self):
        with self.assertRaises(AIProviderError):
            OpenAICompatibleProvider()

    @override_settings(AI_LLM_BASE_URL='https://user:password@example.com/v1')
    def test_embedded_url_credentials_not_allowed(self):
        with self.assertRaises(AIProviderError):
            OpenAICompatibleProvider()


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v2')
class AIAccessIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name='Mars', slug='mars')
        cls.branch = Branch.objects.create(company=cls.company, name='Arena', code='arena')
        cls.branch2 = Branch.objects.create(company=cls.company, name='Other', code='other')

        def user(email, role, branch):
            return User.objects.create_user(email=email, password='a-very-long-password',
                                            first_name=email.split('@')[0], last_name='Test',
                                            role=role, company=cls.company, branch=branch,
                                            must_change_password=False)

        cls.qa = user('qa@example.com', User.Role.QA, cls.branch)
        cls.tl1 = user('tl1@example.com', User.Role.TEAM_LEADER, cls.branch)
        cls.tl2 = user('tl2@example.com', User.Role.TEAM_LEADER, cls.branch)
        cls.pm = user('pm@example.com', User.Role.PROJECT_MANAGER, cls.branch)
        cls.supervisor = user('supervisor@example.com', User.Role.SUPERVISOR, cls.branch)
        cls.other_supervisor = user('othersup@example.com', User.Role.SUPERVISOR, cls.branch2)
        cls.dialer = Dialer.objects.create(branch=cls.branch, name='Dialer One', api_url='https://example.com/api',
                                          api_username='qa')
        cls.p1 = DialerCampaign.objects.create(dialer=cls.dialer, campaign='CAMP-A', project_name='Project A')
        cls.p2 = DialerCampaign.objects.create(dialer=cls.dialer, campaign='CAMP-B', project_name='Project B')
        cls.team1 = Team.objects.create(branch=cls.branch, team_leader=cls.tl1, name='Team One')
        cls.team2 = Team.objects.create(branch=cls.branch, team_leader=cls.tl2, name='Team Two')
        for who, project in [(cls.tl1, cls.p1), (cls.tl2, cls.p2), (cls.pm, cls.p1)]:
            QAProjectAssignment.objects.create(qa=who, dialer_campaign=project)
        cls.reviews = []
        for idx, (team, campaign, agent, critical) in enumerate([
            (cls.team1, 'CAMP-A', 'agent001', ['wasted_lead']),
            (cls.team1, 'CAMP-A', 'agent001', ['wasted_lead']),
            (cls.team2, 'CAMP-B', 'agent002', ['misrepresentation']),
        ]):
            call = CallEvent.objects.create(
                dialer=cls.dialer, branch=cls.branch, team=team, campaign=campaign,
                event_key=f'call-key-{idx}', event_type=CallEvent.EventType.DISPOSITION,
                agent_user=agent, agent_name=f'Agent {agent}',
            )
            review = Review.objects.create(call=call, reviewer=cls.qa, team_leader=team.team_leader,
                                           status=Review.Status.COMPLETED,
                                           completed_at=timezone.now() - timedelta(days=1),
                                           score=75, leader_status=Review.LeaderStatus.PENDING,
                                           critical_errors=critical,
                                           scores={'professional_greeting': 0})
            cls.reviews.append(review)

    def test_role_and_project_scope_cannot_be_overridden_by_llm(self):
        self.assertEqual(permitted_reviews(self.tl1).count(), 2)
        self.assertEqual(permitted_reviews(self.pm).count(), 2)
        self.assertEqual(permitted_reviews(self.supervisor).count(), 3)
        self.assertEqual(permitted_reviews(self.other_supervisor).count(), 0)
        with self.assertRaises(PermissionDenied):
            permitted_reviews(self.qa)

    def test_tool_recurrence_reuses_scoped_reports(self):
        self.assertEqual(len(invoke('find_repeat_critical_errors', self.tl1, {})['matches']), 1)
        self.assertEqual(len(invoke('find_repeat_critical_errors', self.pm, {})['matches']), 1)
        self.assertEqual(len(invoke('find_repeat_critical_errors', self.tl2, {})['matches']), 0)
        details = invoke('get_review_details', self.tl1, {'review_id': str(self.reviews[2].pk)})
        self.assertEqual(details, {'found': False})
        details = invoke('get_review_details', self.tl1, {'review_id': str(self.reviews[0].pk)})
        self.assertTrue(details['found'])
        self.assertNotIn('phone_number', details)

    def test_zero_defect_is_hidden_from_team_leader_tools_and_visible_to_project_manager(self):
        review = self.reviews[0]
        review.evaluation_type = Review.EvaluationType.ZERO_DEFECT
        review.score = None
        review.critical_errors = []
        review.rating = Review.Rating.GOOD
        review.outcome = Review.Outcome.GOOD_CALL
        review.leader_status = Review.LeaderStatus.CLOSED
        review.save()
        self.assertEqual(invoke('get_review_details', self.tl1, {'review_id': str(review.pk)}), {'found': False})
        details = invoke('get_review_details', self.pm, {'review_id': str(review.pk)})
        self.assertTrue(details['found'])
        self.assertEqual(invoke('get_qa_overview', self.tl1, {})['metrics']['evaluations'], 1)
        metrics = invoke('get_qa_overview', self.pm, {})['metrics']
        self.assertEqual(metrics['evaluations'], 2)
        self.assertEqual(metrics['scored'], 1)

    def test_filters_do_not_escalate_scope(self):
        data = invoke('get_qa_overview', self.pm, {'project_name': 'Project B'})
        self.assertEqual(data['metrics']['evaluations'], 0)
        with self.assertRaises(ValidationError):
            invoke('get_qa_overview', self.pm, {'role': 'administrator'})
        with self.assertRaises(ValidationError):
            invoke('find_pending_reviews', self.pm, {'limit': 999})

    def test_identity_digest_changes_when_project_assignment_changes(self):
        before = scope_digest(self.pm)
        QAProjectAssignment.objects.create(qa=self.pm, dialer_campaign=self.p2)
        self.assertNotEqual(before, scope_digest(self.pm))

    def test_conversation_owner_and_scope(self):
        conversation = AIConversation.objects.create(user=self.tl1, scope_digest=scope_digest(self.tl1))
        self.client.force_login(self.tl2)
        response = self.client.get(reverse('ai-conversation-detail', kwargs={'pk': conversation.pk}))
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.tl1)
        response = self.client.get(reverse('ai-conversation-detail', kwargs={'pk': conversation.pk}))
        self.assertEqual(response.status_code, 200)
        QAProjectAssignment.objects.filter(qa=self.tl1).delete()
        response = self.client.get(reverse('ai-conversation-detail', kwargs={'pk': conversation.pk}))
        self.assertEqual(response.status_code, 404)

    def test_agentic_tool_round_trip_returns_verified_review_ids(self):
        from .orchestrator import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'role': 'assistant', 'content': None, 'tool_calls': [
                {'type': 'function', 'id': 'tc-1', 'function': {
                    'name': 'find_pending_reviews', 'arguments': json.dumps({'limit': 5})}}
            ]}, finish_reason='tool_calls'),
            Completion(message={'role': 'assistant', 'content': 'Reports await leader review.'},
                       finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.orchestrator.get_provider', return_value=provider):
            result = run_ai(self.tl1, 'Which reports are pending leader review?')
        self.assertIn('find_pending_reviews', result['tools_used'])
        self.assertTrue(result['evidence'])
        self.assertTrue(all(e['review_id'] in {str(r.pk) for r in self.reviews[:2]}
                            for e in result['evidence']))
        # The backlog response is rendered deterministically; no second LLM narration call.
        self.assertEqual(provider.complete.call_count, 1)

    def test_model_answer_without_qa_tool_is_not_accepted(self):
        from .orchestrator import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        provider = Mock()
        provider.complete.return_value = Completion(message={'role': 'assistant',
            'content': 'An unsupported factual claim'}, finish_reason='stop')
        with patch('apps.ai_assistant.orchestrator.get_provider', return_value=provider):
            result = run_ai(self.tl1, 'Which leader is overdue?')
        self.assertNotIn('unsupported', result['answer'])
        self.assertTrue(result['evidence'])  # sourced from Django, not the unsupported text

    def test_qa_cannot_use_ai_endpoints(self):
        self.client.force_login(self.qa)
        self.assertEqual(self.client.get(reverse('ai-metadata')).status_code, 403)

    @patch('apps.ai_assistant.views.run_ai')
    def test_chat_endpoint_persists_owner_only_conversation(self, mock_run):
        mock_run.return_value = {
            'answer': '2 reports pending',
            'evidence': [{'review_id': str(self.reviews[0].pk), 'tool': 'find_pending_reviews'}],
            'tools_used': ['find_pending_reviews'],
        }
        self.client.force_login(self.tl1)
        response = self.client.post(reverse('ai-chat'), data=json.dumps({'message': 'How many pending?'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AIConversation.objects.filter(user=self.tl1).count(), 1)
        self.assertEqual(AIMessage.objects.count(), 2)
        stored = AIMessage.objects.get(role=AIMessage.Role.ASSISTANT)
        self.assertEqual(stored.evidence, mock_run.return_value['evidence'])
        self.assertEqual(stored.tools_used, ['find_pending_reviews'])
        detail_url = reverse('ai-conversation-detail', kwargs={'pk': response.json()['conversation_id']})
        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['messages'][1]['evidence'], stored.evidence)
        self.client.force_login(self.tl2)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        mock_run.assert_called_once()

    @override_settings(AI_ENABLED=False)
    def test_disabled_by_default(self):
        self.client.force_login(self.pm)
        response = self.client.post(reverse('ai-chat'), data=json.dumps({'message': 'Hello'}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 503)


class SemanticPlanTests(SimpleTestCase):
    def test_week_is_reporting_cohort_not_backlog_exclusion(self):
        from .planning import _validated, _fallback
        plan = _fallback("Which team leaders have pending QA reports this week?")
        self.assertEqual(plan.intent, 'review_backlog')
        self.assertEqual(plan.period, 'this_week')
        self.assertEqual(plan.backlog_mode, 'current_backlog')
        self.assertEqual(_fallback('Which agents repeated the same mistake?').intent,
                         'recurring_mistakes')
        with self.assertRaises(ValidationError):
            _validated({'intent': 'review_backlog', 'period': 'last_30_days',
                        'role': 'administrator'})

    def test_llm_plan_must_be_typed_and_has_no_permission_fields(self):
        from unittest.mock import Mock
        from .planning import plan_question, PLAN_TOOL
        from .provider import Completion
        provider = Mock()
        provider.complete.return_value = Completion(message={
            'tool_calls': [{'type':'function', 'id':'plan-1', 'function': {
                'name':'submit_query_plan', 'arguments':json.dumps({
                    'intent':'review_backlog', 'period':'this_week',
                    'backlog_mode':'current_backlog', 'company_name':'Mars',
                    'branch_name':'Arena'})}}]}, finish_reason='tool_calls')
        plan = plan_question(provider, 'Who is late with reviews in Mars Arena this week?')
        self.assertEqual(plan.company_name, 'Mars')
        self.assertEqual(plan.branch_name, 'Arena')
        self.assertEqual(plan.backlog_mode, 'current_backlog')
        self.assertFalse('role' in PLAN_TOOL['function']['parameters']['properties'])


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v2')
class V2BacklogIntegrationTests(AIAccessIntegrationTests):
    def test_current_backlog_includes_old_pending_reviews(self):
        from apps.analytics.services.reviews import find_pending_reviews
        from .orchestrator import _render_backlog
        old = self.reviews[0]
        old.completed_at = timezone.now() - timedelta(days=63)
        old.save(update_fields=['completed_at'])
        recent = self.reviews[1]
        recent.completed_at = timezone.now()
        recent.save(update_fields=['completed_at'])
        result = find_pending_reviews(user=self.tl1, mode='current_backlog', limit=10)
        self.assertEqual(result['total_pending'], 2)
        self.assertEqual(result['carried_over'], 1)
        self.assertEqual(result['submitted_in_period_pending'], 1)
        self.assertIn('1 were submitted outside', _render_backlog(result))
        recent_only = find_pending_reviews(user=self.tl1, mode='submitted_in_period', limit=10)
        self.assertEqual(recent_only['total_pending'], 1)
        self.assertTrue(result['completeness']['aggregate_complete'])
        self.assertEqual(find_pending_reviews(user=self.tl2)['total_pending'], 1)
        self.assertEqual(find_pending_reviews(user=self.pm)['total_pending'], 2)
        self.assertEqual(find_pending_reviews(user=self.other_supervisor)['total_pending'], 0)

    def test_cannot_resolve_other_team_by_name(self):
        from .planning import QueryPlan
        from .orchestrator import _resolve_identity
        result, issue = _resolve_identity(self.tl1, QueryPlan(
            intent='team_ranking', team_name='Team Two'))
        self.assertIsNone(result)
        self.assertIn('No accessible team', issue)

    def test_zero_pending_is_not_claim_all_reviews_completed(self):
        from apps.analytics.services.reviews import find_pending_reviews
        from .orchestrator import _render_backlog
        result = find_pending_reviews(user=self.other_supervisor)
        self.assertEqual(result['total_pending'],0)
        self.assertIn('does not establish', _render_backlog(result))


class V3CalendarAndToolsTests(SimpleTestCase):
    """No model output can override the Django business calendar or tool whitelist."""
    def test_natural_date_phrases_use_authoritative_calendar(self):
        from datetime import date
        from .timeframes import resolve_window
        now = date(2026, 10, 9)
        self.assertEqual((resolve_window('critical errors yesterday', today=now).start,
                          resolve_window('critical errors yesterday', today=now).end),
                         (date(2026, 10, 8), date(2026, 10, 8)))
        period = resolve_window('not reviewed in past 4 days', today=now)
        self.assertEqual((period.start, period.end), (date(2026, 10, 6), now))
        self.assertEqual(resolve_window('yesteray', today=now).start, date(2026, 10, 8))
        self.assertEqual(resolve_window('past four days', today=now).start, date(2026, 10, 6))
        self.assertEqual(resolve_window('what about last week', today=now).start,
                         date(2026, 9, 28))
        with self.assertRaises(ValueError):
            resolve_window('last 400 days', today=now)

    def test_tool_selection_rejects_unapproved_names(self):
        from .investigation import _names_from_call, _catalog
        from .provider import Completion
        catalog = _catalog()
        answer = Completion(message={'tool_calls': [{'type': 'function',
            'function': {'name': 'select_qa_tools',
                         'arguments':json.dumps({'names':['execute_sql']})}}]}, finish_reason='tool_calls')
        self.assertIsNone(_names_from_call(answer, 'select_qa_tools', catalog, 6))
        self.assertIn('lookup_visible_people', catalog)

    def test_unverified_factual_numbers_are_detected(self):
        from .investigation import _unverified_numbers
        evidence = [{'total_pending': 12, 'submitted_in_period_pending': 2}]
        self.assertFalse(_unverified_numbers('12 pending, 2 were submitted on 2026-10-08.', evidence))
        self.assertEqual(_unverified_numbers('There are 999 pending.', evidence), ['999'])


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3')
class V3InvestigationIntegrationTests(TestCase):
    """Real authorized ORM fixtures, with only the provider transport mocked."""

    @classmethod
    def setUpTestData(cls):
        # Use exactly the established team/project fixtures, without duplicating V2 tests.
        AIAccessIntegrationTests.setUpTestData.__func__(cls)
    def test_person_role_resolution_uses_authorized_tl_records(self):
        from .person_tools import lookup_visible_people
        matches = lookup_visible_people(user=self.pm, search='tl1 Test', role='any')['matches']
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['role'], 'team_leader')
        self.assertEqual(matches[0]['id'], str(self.tl1.pk))
        self.assertFalse(lookup_visible_people(user=self.pm,
                                               search='tl2 Test', role='team_leader')['matches'])
        self.assertFalse(lookup_visible_people(user=self.pm,
                                               search='tl3 Test', role='team_leader')['matches'])
        typo = lookup_visible_people(user=self.pm, search='tl1 Tset', role='team_leader')
        self.assertEqual(len(typo['matches']), 1)
        self.assertEqual(typo['matches'][0]['match_type'], 'approximate')
        self.assertEqual(invoke('find_pending_reviews', self.pm,
                                {'team_leader_id': str(self.tl2.pk)})['total_pending'], 0)

    def test_approximate_person_requires_confirmation_not_an_id_grant(self):
        from .investigation import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls':[{'id':'select', 'type':'function','function':{
                'name':'select_qa_tools','arguments':'{"names":["lookup_visible_people","find_pending_reviews"]}'}}]},
                finish_reason='tool_calls'),
            Completion(message={'tool_calls':[{'id':'lookup','type':'function','function':{
                'name':'lookup_visible_people',
                'arguments':'{"search":"tl1 Tset","role":"team_leader"}'}}]},
                finish_reason='tool_calls'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider):
            result = run_ai(self.pm, 'How many reports are pending for tl1 Tset?')
        self.assertEqual(result['interpretation']['intent'], 'clarification')
        self.assertIn('tl1 Test', result['answer'])
        self.assertIn('confirm', result['answer'].casefold())
        self.assertEqual(result['tools_used'], ['lookup_visible_people'])
        self.assertFalse(result['evidence'])
        self.assertEqual(provider.complete.call_count, 2)

    def test_person_lookup_uses_actual_portal_user_fields(self):
        from .person_tools import lookup_visible_people
        from django.core.exceptions import FieldDoesNotExist
        # Execute the ORM query; compiling only wouldn't catch a non-existent
        # User.username, which is deliberately removed from this project.
        self.assertIsNone(User._meta.get_field('email').remote_field)
        with self.assertRaises(FieldDoesNotExist):
            User._meta.get_field('username')
        by_name = lookup_visible_people(user=self.pm, search='tl1 Test', role='team_leader')
        by_first = lookup_visible_people(user=self.pm, search='tl1', role='team_leader')
        by_email = lookup_visible_people(user=self.pm, search='tl1@example.com', role='team_leader')
        for result in (by_name, by_first, by_email):
            self.assertEqual(len(result['matches']), 1)
            self.assertEqual(result['matches'][0]['id'], str(self.tl1.pk))
        self.assertFalse(lookup_visible_people(user=self.pm, search='tl2@example.com',
                                               role='team_leader')['matches'])
        self.assertEqual(lookup_visible_people(user=self.pm, search='agent001', role='agent')
                         ['matches'][0]['agent_user'], 'agent001')

    def test_invalid_database_lookup_fails_closed(self):
        from django.core.exceptions import FieldError
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion, AIProviderError
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls':[{'id':'choose','type':'function','function':{
                'name':'select_qa_tools', 'arguments':'{"names":["lookup_visible_people"]}'}}]},
                       finish_reason='tool_calls'),
            Completion(message={'tool_calls':[{'id':'find','type':'function','function':{
                'name':'lookup_visible_people', 'arguments':'{"search":"tl1 Test"}'}}]},
                       finish_reason='tool_calls'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider), \
             patch('apps.ai_assistant.investigation.invoke', side_effect=FieldError('broken lookup')):
            with self.assertRaises(AIProviderError):
                run_ai(self.pm, 'Find team leader tl1 Test')

    @override_settings(SECURE_SSL_REDIRECT=False)
    def test_broken_database_tool_returns_503_not_500(self):
        from django.core.exceptions import FieldError
        from unittest.mock import Mock
        from .provider import Completion
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls':[{'id':'choose','type':'function','function':{
                'name':'select_qa_tools', 'arguments':'{"names":["lookup_visible_people"]}'}}]},
                       finish_reason='tool_calls'),
            Completion(message={'tool_calls':[{'id':'find','type':'function','function':{
                'name':'lookup_visible_people', 'arguments':'{"search":"tl1 Test"}'}}]},
                       finish_reason='tool_calls'),
        ]
        self.client.force_login(self.pm)
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider), \
             patch('apps.ai_assistant.investigation.invoke', side_effect=FieldError('broken lookup')):
            response = self.client.post(reverse('ai-chat'),
                                        data=json.dumps({'message':'Find tl1 Test'}),
                                        content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('broken lookup', response.content.decode())

    def test_model_driven_leader_lookup_then_backlog(self):
        from .investigation import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        def tc(name, args, identifier):
            return {'type': 'function', 'id': identifier,
                    'function': {'name': name, 'arguments': json.dumps(args)}}
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls': [tc('select_qa_tools',
                {'names': ['find_pending_reviews', 'lookup_visible_people']}, 'select')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('lookup_visible_people',
                {'search': 'tl1 Test', 'role': 'team_leader'}, 'look')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('find_pending_reviews',
                {'team_leader_id': str(self.tl1.pk), 'date_from': '2023-10-01'}, 'pending')]},
                finish_reason='tool_calls'),
            Completion(message={'content': 'tl1 Test has 2 pending QA reports.'}, finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider):
            result = run_ai(self.pm, 'How many reports has tl1 Test not reviewed?')
        self.assertEqual(result['tools_used'], ['lookup_visible_people', 'find_pending_reviews'])
        self.assertIn('2 pending', result['answer'])
        self.assertTrue(result['evidence'])
        self.assertEqual(result['context_state']['last_person']['role'], 'team_leader')
        self.assertEqual(provider.complete.call_count, 4)

    def test_yesterday_cannot_be_replaced_by_model_old_dates(self):
        from datetime import date
        from .timeframes import TimeWindow
        from .investigation import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls':[{'id':'choose','type':'function','function':{
                'name':'select_qa_tools', 'arguments':'{"names":["get_critical_error_summary"]}'}}]},
                       finish_reason='tool_calls'),
            Completion(message={'tool_calls':[{'id':'errors','type':'function','function':{
                'name':'get_critical_error_summary',
                'arguments':'{"date_from":"2023-10-01","date_to":"2023-10-05"}'}}]},
                       finish_reason='tool_calls'),
            Completion(message={'content':'I found 0 critical errors yesterday.'},finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider), \
             patch('apps.ai_assistant.investigation.resolve_window', return_value=TimeWindow(
                date(2026,10,8), date(2026,10,8), 'yesterday', True)), \
             patch('apps.ai_assistant.investigation.invoke', wraps=invoke) as database_tool:
            result = run_ai(self.pm, 'How many critical violations yesterday?')
        arguments = database_tool.call_args.args[2]
        self.assertEqual(arguments['date_from'], '2026-10-08')
        self.assertEqual(arguments['date_to'], '2026-10-08')
        self.assertEqual(result['interpretation']['date_from'], '2026-10-08')

    def test_unsupported_numeric_claim_does_not_reach_user(self):
        from .investigation import run_ai
        from .provider import Completion
        from unittest.mock import Mock
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls':[{'id':'choose','type':'function','function':{
                'name':'select_qa_tools', 'arguments':'{"names":["find_pending_reviews"]}'}}]},
                       finish_reason='tool_calls'),
            Completion(message={'tool_calls':[{'id':'pending','type':'function','function':{
                'name':'find_pending_reviews', 'arguments':'{}'}}]}, finish_reason='tool_calls'),
            Completion(message={'content':'There are 999 pending reports.'},finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider):
            result = run_ai(self.pm, 'How many reports pending?')
        self.assertNotIn('999', result['answer'])
        self.assertIn('replaced', result['warnings'][0])


class V3ContextAndConversationTests(SimpleTestCase):
    """Static domain intent constraints: Qwen cannot reinterpret known metrics."""
    def test_typo_normalization_does_not_change_business_names(self):
        from .investigation import _normalize_question, _requires_tool, _rubric_outline
        q = _normalize_question('how many evalutions for ArenMedicare dialr yesteray?')
        self.assertIn('evaluations', q)
        self.assertIn('ArenMedicare', q)
        self.assertIn('dialer', q)
        self.assertIn('yesterday', q)
        self.assertEqual(_requires_tool(q), 'list_visible_dialers')
        self.assertIn('Active listening', _rubric_outline())

    def test_never_use_an_error_type_table_to_identify_worst_agent(self):
        from .investigation import _requires_tool, _safe_fallback, _followup
        self.assertEqual(_requires_tool('which agent had the most critical violations?'), 'rank_agents')
        self.assertEqual(_requires_tool('how many calls were received in Call Library this week'),
                         'get_call_library_overview')
        self.assertFalse(_followup('How many evaluations for our projects?'))
        self.assertTrue(_followup('and Asim Jamal?'))
        self.assertIn('does not identify', _safe_fallback([{
            'name': 'get_critical_error_summary', 'arguments': {},
            'data': {'reviews_with_critical_errors': 7}}]))

    def test_safe_answer_fallback_for_volumes_and_rankings(self):
        from .investigation import _safe_fallback, _is_greeting
        self.assertTrue(_is_greeting('are you there?'))
        self.assertIn('2 call-library records', _safe_fallback([{
            'name': 'get_call_library_overview', 'arguments': {}, 'data': {'calls_received':2}}]))
        self.assertIn('agent001', _safe_fallback([{
            'name': 'rank_agents', 'arguments': {}, 'data': {'metric': 'critical_error_reviews',
                'agents': [{'agent_name':'Agent 001', 'agent_user':'agent001', 'critical_error_reviews':2}]}}]))


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3')
class V3AuthorizedContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        AIAccessIntegrationTests.setUpTestData.__func__(cls)

    def test_dialer_is_not_project_and_exact_filter_narrows_reports(self):
        from apps.analytics.services.context import list_visible_dialers
        found = list_visible_dialers(user=self.pm, search='Dialer One')
        self.assertEqual(len(found['dialers']), 1)
        self.assertEqual(found['dialers'][0]['evaluations'], 2)
        self.assertEqual(found['dialers'][0]['match'], 'exact')
        self.assertEqual(invoke('get_qa_overview', self.pm, {
            'dialer_id': str(self.dialer.id)})['metrics']['evaluations'], 2)
        self.assertFalse(list_visible_dialers(user=self.other_supervisor,
                                             search='Dialer One')['dialers'])
        self.assertFalse(list_visible_dialers(user=self.pm,
                                              search='Unknown Dialer')['dialers'])

    def test_typo_person_search_only_within_authorized_report_scope(self):
        from .person_tools import lookup_visible_people
        found = lookup_visible_people(user=self.pm, search='tl1 Tset', role='team_leader')
        self.assertEqual(len(found['matches']), 1)
        self.assertEqual(found['matches'][0]['match_type'], 'approximate')
        self.assertEqual(found['matches'][0]['id'], str(self.tl1.id))
        invisible = lookup_visible_people(user=self.pm, search='tl2 Tset', role='team_leader')
        self.assertFalse(invisible['matches'])

    def test_call_library_uses_existing_visibility_and_counts_unreviewed_calls(self):
        from apps.analytics.services.context import get_call_library_overview
        extra = CallEvent.objects.create(
            dialer=self.dialer, branch=self.branch, team=self.team1, campaign='CAMP-A',
            event_key='additional-unreviewed-call', event_type=CallEvent.EventType.DISPOSITION)
        result = get_call_library_overview(user=self.pm)
        self.assertEqual(result['calls_received'], 3)
        self.assertEqual(get_call_library_overview(user=self.tl1)['calls_received'], 3)
        self.assertEqual(get_call_library_overview(user=self.other_supervisor)['calls_received'], 0)
        with self.assertRaises(PermissionDenied):
            get_call_library_overview(user=self.qa)

    @override_settings(AI_SEND_REVIEW_FEEDBACK=False)
    def test_qa_heading_context_by_review_id_is_scoped_and_redacted_by_default(self):
        from apps.analytics.services.context import get_review_qa_context, get_qa_feedback_examples
        report = self.reviews[0]
        report.improvement_areas = 'Tell caller +1 (202) 555-0123 to say yes.'
        report.save(update_fields=['improvement_areas'])
        detail = get_review_qa_context(user=self.pm, review_id=str(report.pk))
        self.assertTrue(detail['found'])
        self.assertTrue(detail['headings'])
        self.assertIn('disabled', detail['reviewer_feedback'])
        self.assertFalse(get_review_qa_context(user=self.other_supervisor,
                                                review_id=str(report.pk))['found'])
        self.assertEqual(get_qa_feedback_examples(user=self.pm)['examples'], [])

    @override_settings(AI_SEND_REVIEW_FEEDBACK=True)
    def test_review_written_improvement_context_is_bounded_and_redacted(self):
        from apps.analytics.services.context import get_review_qa_context, get_qa_feedback_examples
        review = self.reviews[0]
        review.improvement_areas = 'Coach opening. Contact 2025550123 or coach@example.org.'
        review.expected_behavior = 'Use professional greeting.'
        review.save(update_fields=['improvement_areas', 'expected_behavior'])
        detail = get_review_qa_context(user=self.pm, review_id=str(review.pk))
        self.assertIn('Coach opening', detail['reviewer_feedback']['improvement_areas'])
        self.assertNotIn('2025550123', detail['reviewer_feedback']['improvement_areas'])
        self.assertNotIn('coach@example.org', detail['reviewer_feedback']['improvement_areas'])
        sample = get_qa_feedback_examples(user=self.pm)
        self.assertEqual(len(sample['examples']), 1)
        self.assertTrue(sample['sample_only'])
        self.assertFalse(get_qa_feedback_examples(user=self.other_supervisor)['examples'])

    @override_settings(AI_SEND_REVIEW_FEEDBACK=False)
    def test_historical_scorecard_snapshot_is_preferred_over_current_policy(self):
        from apps.analytics.services.context import get_review_qa_context
        review = self.reviews[0]
        review.scorecard_snapshot = {'categories': [
            {'key': 'opening', 'label': 'Historical Opening', 'criteria': [
                {'key': 'professional_greeting', 'label': 'Historical Greeting', 'max_score': 7}]}]}
        review.scorecard_version = 'old-version'
        review.save(update_fields=['scorecard_snapshot', 'scorecard_version'])
        detail = get_review_qa_context(user=self.pm, review_id=str(review.pk))
        self.assertEqual(detail['rubric_source'], 'review_snapshot')
        self.assertEqual(detail['headings'][0]['heading'], 'Historical Opening')
        self.assertEqual(detail['headings'][0]['subheadings'][0]['max_points'], 7)

    def test_singular_our_project_does_not_expand_to_other_projects(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        def tc(name, args, identifier):
            return {'type': 'function', 'id': identifier,
                    'function': {'name': name, 'arguments': json.dumps(args)}}
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls': [tc('select_qa_tools',
                {'names': ['get_qa_overview']}, 'sel')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('get_qa_overview',
                {'project_name': 'Project B'}, 'overview')]}, finish_reason='tool_calls'),
            Completion(message={'content': 'There were 2 completed evaluations for the project.'},
                       finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider), \
             patch('apps.ai_assistant.investigation.invoke', wraps=invoke) as database_tool:
            result = run_ai(self.pm, 'How many evaluations were submitted in total for our project?')
        self.assertEqual(database_tool.call_args.args[2]['project_name'], 'Project A')
        self.assertIn('2', result['answer'])

    def test_model_wrong_violation_ranking_metric_is_corrected_by_django(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        def tc(name, args, identifier):
            return {'type': 'function', 'id': identifier,
                    'function': {'name': name, 'arguments': json.dumps(args)}}
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls': [tc('select_qa_tools',
                {'names': ['rank_agents']}, 'sel')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('rank_agents',
                {'metric': 'average_score', 'order': 'best'}, 'rank')]}, finish_reason='tool_calls'),
            Completion(message={'content': 'Agent agent001 had 2 critical error reviews.'},
                       finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider), \
             patch('apps.ai_assistant.investigation.invoke', wraps=invoke) as database_tool:
            run_ai(self.pm, 'Which agent had the most violations?')
        self.assertEqual(database_tool.call_args.args[2]['metric'], 'critical_error_reviews')
        self.assertEqual(database_tool.call_args.args[2]['order'], 'worst')

    def test_approximate_dialer_name_asks_confirmation_instead_of_guessing_total(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        def tc(name, args, identifier):
            return {'type': 'function', 'id': identifier,
                    'function': {'name': name, 'arguments': json.dumps(args)}}
        provider = Mock()
        provider.complete.side_effect = [
            Completion(message={'tool_calls': [tc('select_qa_tools',
                {'names': ['list_visible_dialers']}, 'sel')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('list_visible_dialers',
                {'search': 'Dialer On'}, 'dialer')]}, finish_reason='tool_calls'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=provider):
            result = run_ai(self.pm, 'How many evaluations for Dialer On dialer?')
        self.assertIn('Which dialer', result['answer'])
        self.assertIn('Dialer One', result['answer'])
        self.assertNotIn('2 evaluations', result['answer'])
        self.assertEqual(result['interpretation']['intent'], 'clarification')


class V3RankingSemanticsTests(SimpleTestCase):
    """Pure, reproducible conversational answer contracts (no provider involved)."""
    def test_past_two_weeks_is_14_days_not_thirty(self):
        from datetime import date
        from .timeframes import resolve_window
        for phrase in ('past 2 weeks', 'last two weeks', 'over the last 2 weeks', 'last fortnight'):
            window = resolve_window('agents with most problems ' + phrase,
                                    today=date(2026, 10, 9))
            self.assertEqual(window.start.isoformat(), '2026-09-26', phrase)
            self.assertEqual(window.end.isoformat(), '2026-10-09', phrase)
            self.assertTrue(window.explicit)

    def test_ties_remain_ties_in_next_and_third_place_answers(self):
        from .conversation_analysis import describe_ranking
        ranking = {'metric': 'critical_error_reviews', 'order': 'worst', 'agents': [
            {'agent_user': '8005', 'agent_name': 'Zaran', 'critical_error_reviews': 4},
            {'agent_user': '8016', 'agent_name': 'Mubashir', 'critical_error_reviews': 4},
            {'agent_user': '8098', 'agent_name': 'Shawn', 'critical_error_reviews': 4},
            {'agent_user': '8102', 'agent_name': 'Ahmed TR', 'critical_error_reviews': 4},
            {'agent_user': '8042', 'agent_name': 'Amir', 'critical_error_reviews': 3},
            {'agent_user': '8051', 'agent_name': 'Sheryar', 'critical_error_reviews': 2},
        ]}
        next_answer = describe_ranking(ranking, "who's next to Zaran?")
        self.assertIn('share rank 1', next_answer)
        self.assertIn('Next distinct rank (5)', next_answer)
        self.assertIn('Amir', next_answer)
        third = describe_ranking(ranking, 'the third worst guy?')
        self.assertIn('Distinct group #3 (competition rank 6)', third)
        self.assertIn('Sheryar', third)
        top = describe_ranking(ranking, 'top 10 worst agents')
        self.assertIn('Zaran', top)
        self.assertIn('Sheryar', top)
        self.assertEqual(top.count('- Rank '), 6)

    def test_new_subject_does_not_reuse_agent_ranking(self):
        from .conversation_analysis import is_ranking_followup
        prev = {'last_analysis': {'kind': 'agent_ranking',
                                  'metric': 'critical_error_reviews', 'order': 'worst'}}
        self.assertTrue(is_ranking_followup("and who's next after Zaran?", prev))
        self.assertTrue(is_ranking_followup('and the 3rd worst?', prev))
        self.assertFalse(is_ranking_followup('Who is the worst team leader?', prev))
        self.assertFalse(is_ranking_followup('Who has the lowest average score?', prev))


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3')
class V3ConversationalRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        AIAccessIntegrationTests.setUpTestData.__func__(cls)

    def test_ranking_followup_requeries_authorized_reports_without_model(self):
        from .investigation import run_ai
        from .timeframes import resolve_window
        window = resolve_window('past 2 weeks')
        previous = {'last_analysis': {'kind': 'agent_ranking',
                    'metric': 'critical_error_reviews', 'order': 'worst', 'filters': {},
                    'period': {'date_from': window.start.isoformat(),
                               'date_to': window.end.isoformat()}},
                    'time_window': {'date_from': window.start.isoformat(),
                                    'date_to': window.end.isoformat()}}
        conversation = AIConversation.objects.create(
            user=self.pm, scope_digest=scope_digest(self.pm), context_state=previous)
        with patch('apps.ai_assistant.investigation.get_provider') as model:
            result = run_ai(self.pm, 'who is the 2nd worst?', conversation=conversation)
        model.assert_not_called()
        self.assertIn('distinct', result['answer'].casefold())
        self.assertEqual(result['interpretation']['date_from'], window.start.isoformat())
        self.assertEqual(result['context_state']['last_analysis']['metric'], 'critical_error_reviews')
        # The stored query specification cannot grant access to another branch.
        other_conversation = AIConversation.objects.create(
            user=self.other_supervisor, scope_digest=scope_digest(self.other_supervisor),
            context_state=previous)
        with patch('apps.ai_assistant.investigation.get_provider') as model:
            other = run_ai(self.other_supervisor, 'the second worst?',
                           conversation=other_conversation)
        model.assert_not_called()
        self.assertIn('No agents', other['answer'])

    def test_ranked_summary_not_first_agent_only_when_provider_hallucinates(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        def tc(name, params, key):
            return {'id': key, 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(params)}}
        model = Mock()
        model.complete.side_effect = [
            Completion(message={'tool_calls': [tc('select_qa_tools',
                {'names': ['rank_agents']}, 'selected')]}, finish_reason='tool_calls'),
            Completion(message={'tool_calls': [tc('rank_agents',
                {'metric': 'critical_error_reviews', 'limit': 1}, 'rank')]}, finish_reason='tool_calls'),
            Completion(message={'content': '999 agents were bad and all have 1000 critical reviews.'},
                       finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=model):
            result = run_ai(self.pm, 'Give me the top 10 worst agents in the past 2 weeks')
        self.assertEqual(result['interpretation']['label'], 'past 2 weeks')
        self.assertNotIn('999', result['answer'])
        self.assertIn('Agent agent001', result['answer'])
        self.assertIn('critical error', result['answer'])
        self.assertEqual(result['context_state']['last_analysis']['metric'], 'critical_error_reviews')

    def test_model_skipping_tools_uses_real_repeat_issue_data(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        model = Mock()
        model.complete.side_effect = [
            Completion(message={'content': 'I cannot choose.'}, finish_reason='stop'),
            Completion(message={'content': 'I do not know.'}, finish_reason='stop'),
        ]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=model):
            result = run_ai(self.pm, 'Which agent repeatedly made the same mistake again and again?')
        self.assertIn('find_repeated_mistakes', result['tools_used'])
        self.assertIn('Agent agent001', result['answer'])
        self.assertTrue(result['evidence'])

    def test_worst_team_leader_uses_current_pending_not_agent_ranking(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        model = Mock()
        model.complete.side_effect = [Completion(message={'content': ''}, finish_reason='stop'),
                                      Completion(message={'content': ''}, finish_reason='stop')]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=model):
            result = run_ai(self.pm, 'Who is the worst team leader at not reviewing submitted reports?')
        self.assertIn('find_pending_reviews', result['tools_used'])
        self.assertIn('tl1 Test', result['answer'])
        self.assertIn('pending', result['answer'])

    def test_specific_recorded_critical_violation_has_review_evidence(self):
        from unittest.mock import Mock
        from .investigation import run_ai
        from .provider import Completion
        model = Mock()
        model.complete.side_effect = [Completion(message={'content': ''}, finish_reason='stop'),
                                      Completion(message={'content': ''}, finish_reason='stop')]
        with patch('apps.ai_assistant.investigation.get_provider', return_value=model):
            result = run_ai(self.pm, 'What critical violation was recorded for Agent agent001?')
        self.assertIn('get_agent_critical_violations', result['tools_used'])
        self.assertIn('Wasted lead', result['answer'])
        self.assertTrue(result['evidence'])
        self.assertNotIn('phone_number', result['answer'])


class V3TypedSemanticSelectionTests(SimpleTestCase):
    def test_synonymous_semantic_intent_adds_authorized_tool_without_keyword_map(self):
        from .investigation import _semantic_selection, _catalog
        from .provider import Completion
        catalog = _catalog()
        result = Completion(message={'tool_calls': [{'type': 'function',
            'function': {'name': 'select_qa_tools', 'arguments': json.dumps({
                'names': ['get_qa_overview'], 'intent': 'repeated_criteria'})}}]},
            finish_reason='tool_calls')
        selection = _semantic_selection(result, catalog)
        self.assertIn('find_repeated_mistakes', selection['names'])
        self.assertEqual(selection['required'], 'find_repeated_mistakes')

    def test_unsafe_semantic_tool_name_is_rejected(self):
        from .investigation import _semantic_selection, _catalog
        from .provider import Completion
        reply = Completion(message={'tool_calls': [{'type': 'function',
            'function': {'name': 'select_qa_tools', 'arguments': json.dumps({
                'names': ['execute_sql'], 'intent': 'agent_ranking'})}}]},
            finish_reason='tool_calls')
        self.assertIsNone(_semantic_selection(reply, _catalog()))


@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3')
class V3RankingIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        AIAccessIntegrationTests.setUpTestData.__func__(cls)

    def test_agent_display_name_changes_do_not_split_dialer_login(self):
        # Grouping must be dialer+agent_user, not agent_name. A name edit or
        # spelling variation cannot manufacture multiple ranking identities.
        call = self.reviews[1].call
        call.agent_name = 'Updated Display Name'
        call.save(update_fields=['agent_name'])
        ranking = invoke('rank_agents', self.pm,
                         {'metric': 'critical_error_reviews', 'order': 'worst', 'limit': 25})
        self.assertEqual(len(ranking['agents']), 1)
        self.assertEqual(ranking['agents'][0]['agent_user'], 'agent001')
        self.assertEqual(ranking['agents'][0]['critical_error_reviews'], 2)
