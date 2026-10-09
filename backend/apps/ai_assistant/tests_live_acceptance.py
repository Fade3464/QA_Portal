"""Opt-in live provider + real ORM, using ONLY synthetic rows in a test database.

Ordinary CI skips this class. Explicit staging invocation:
AI_LIVE_ACCEPTANCE=1 python manage.py test \
    apps.ai_assistant.tests_live_acceptance --settings=config.ai_test_settings

No real portal data is read. This test exercises the configured language-model
endpoint and therefore consumes inference time. Do not run it with production
settings or reuse a live application database.
"""
import os
from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from . import tests_contract_integration as fixtures
from .access import scope_digest
from .investigation import run_ai
from .models import AIConversation
from apps.calls.models import Review


@skipUnless(os.getenv('AI_LIVE_ACCEPTANCE') == '1', 'Live Qwen acceptance requires explicit opt-in.')
@override_settings(AI_ENABLED=True, AI_ENGINE_VERSION='v3', AI_SEND_REVIEW_FEEDBACK=False)
class LiveQAContractAcceptance(fixtures.ContractFixtures, TestCase):
    def setUp(self):
        if (getattr(settings, 'SETTINGS_MODULE', '') != 'config.ai_test_settings' or
                not str(connection.settings_dict['NAME']).startswith('test_')):
            raise RuntimeError('Live acceptance requires isolated test settings and a test_-prefixed database.')
        self.conv = AIConversation.objects.create(user=self.supervisor,
                     scope_digest=scope_digest(self.supervisor), context_state={})
        self.history = []

    def ask(self, question, *, user=None):
        user = user or self.supervisor
        with timezone.override(user.branch.timezone):
            result = run_ai(user, question, conversation=self.conv, history=self.history)
        self.conv.context_state = result.get('context_state', {})
        self.conv.save(update_fields=['context_state'])
        self.history.extend([{'role':'user','content':question}, {'role':'assistant','content':result['answer']}])
        self.history = self.history[-4:]
        return result

    def complete(self, result, subject):
        self.assertEqual(result['interpretation'].get('result_status'), 'complete', result)
        self.assertEqual(result['interpretation'].get('subject'), subject, result)
        self.assertLessEqual(result['interpretation']['execution']['attempts'], 9)

    def test_team_worst_best_and_next_are_not_agent_rankings(self):
        repeats = max(1, min(3, int(os.getenv('AI_LIVE_REPEATS', '1'))))
        for _ in range(repeats):
            self.conv.context_state = {}; self.history = []
            worst = self.ask('which team has been performing the worst in the past 10 days')
            self.complete(worst, 'team')
            self.assertIn('Team Two', worst['answer']); self.assertEqual(worst['interpretation']['order'], 'worst')
            self.assertNotIn('rank_agents', worst['tools_used'])
            best = self.ask('which team has been performing the best in the past 10 days')
            self.complete(best, 'team')
            self.assertIn('Team One', best['answer']); self.assertEqual(best['interpretation']['order'], 'best')
            self.assertEqual(best['interpretation']['date_from'], worst['interpretation']['date_from'])
            state = dict(self.conv.context_state)
            social = self.ask('how are you?')
            self.assertFalse(social['tools_used']); self.assertFalse(social['evidence'])
            self.assertEqual(self.conv.context_state, state)
            nxt = self.ask("and who's next?")
            self.complete(nxt, 'team'); self.assertIn('Team Two', nxt['answer'])

    def test_collective_backlog_after_individual_has_every_visible_leader(self):
        named = self.ask('How many QA reports are pending for tl1 Test?')
        self.complete(named, 'team_leader'); self.assertIn('3 pending', named['answer'])
        all_leaders = self.ask('Which team leaders have pending QA reports this week?')
        self.complete(all_leaders, 'team_leader')
        self.assertIn('**6**', all_leaders['answer'])
        self.assertIn('tl1 Test', all_leaders['answer']); self.assertIn('tl2 Test', all_leaders['answer'])
        self.assertNotIn('team_leader_id', self.conv.context_state['query_contract']['filters'])

    def test_all_time_includes_old_review_without_fake_cohort_dates(self):
        Review.objects.filter(pk=self.reviews[0].pk).update(completed_at=timezone.now()-timedelta(days=800))
        result = self.ask('Which team leaders have pending QA reports for all time?')
        self.complete(result, 'team_leader')
        self.assertIn('**6**', result['answer'])
        self.assertTrue(result['interpretation']['all_time'])
        self.assertIsNone(result['interpretation']['date_from'])
        self.assertIsNone(result['interpretation']['date_to'])
        self.assertIn('no submission-date cutoff', result['answer'])

    def test_current_explicit_period_wins_over_history(self):
        self.ask('Which team performed the worst in the past 2 weeks?')
        result = self.ask('and which team performed best yesterday?')
        self.complete(result, 'team')
        with timezone.override(self.branch.timezone):
            yesterday = (timezone.localdate()-timedelta(days=1)).isoformat()
        self.assertEqual(result['interpretation']['date_from'], yesterday)
        self.assertEqual(result['interpretation']['date_to'], yesterday)
        self.assertEqual(result['interpretation']['order'], 'best')

    def test_pm_cannot_see_unassigned_team_through_model(self):
        self.conv = AIConversation.objects.create(user=self.pm, scope_digest=scope_digest(self.pm), context_state={})
        result = self.ask('Which team has been performing worst for all time?', user=self.pm)
        self.complete(result, 'team')
        self.assertIn('Team One', result['answer']); self.assertNotIn('Team Two', result['answer'])
        self.assertNotIn('tl2 Test', result['answer'])

    def test_unfamiliar_personal_wording_uses_conversational_channel(self):
        result = self.ask('Does software like you ever need a break?')
        self.assertEqual(result['interpretation'].get('response_kind'), 'conversation', result)
        self.assertFalse(result['tools_used']); self.assertFalse(result['evidence'])
