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
