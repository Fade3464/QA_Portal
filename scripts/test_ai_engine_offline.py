#!/usr/bin/env python3
"""Real investigation controller + actual tool schemas, synthetic in-memory ports.

No Django ORM, live LLM, PostgreSQL, GPU, or production data. Run this in its own
process; the explicit dependency shims are ONLY for this portable test harness.
Use manage.py test for actual Django integration and role isolation.
"""
import ast
from copy import deepcopy
from contextlib import nullcontext
from datetime import date, datetime, timezone as dt_timezone
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
print('OFFLINE CONTROLLER TEST: in-memory domain/provider ports; NOT ORM/GPU integration.', flush=True)

def module(name, **attributes):
    obj = types.ModuleType(name)
    obj.__dict__.update(attributes)
    sys.modules[name] = obj
    return obj

class ValidationError(Exception): pass
class PermissionDenied(Exception): pass
class FieldError(Exception): pass
class DatabaseError(Exception): pass
class AIProviderError(Exception): pass
class Completion:
    def __init__(self, message, finish_reason='stop'):
        self.message, self.finish_reason = message, finish_reason

module('django')
module('django.utils', timezone=types.SimpleNamespace(localdate=lambda: date(2026,10,9),
       now=lambda: datetime(2026,10,9,12,tzinfo=dt_timezone.utc), get_current_timezone=lambda: 'America/New_York'))
module('django.core')
module('django.core.exceptions', FieldError=FieldError)
module('django.db', DatabaseError=DatabaseError)
module('rest_framework')
module('rest_framework.exceptions', PermissionDenied=PermissionDenied, ValidationError=ValidationError)

RIDS = ['00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002']
LID = '00000000-0000-0000-0000-000000000010'
class EvidenceScope:
    def filter(self, **kwargs):
        self.ids = kwargs.get('pk__in', RIDS)
        return self
    def values_list(self, *args, **kwargs):
        return [x for x in self.ids if str(x) in RIDS]
    def exists(self): return True

def access(user):
    if user == 'denied': raise PermissionDenied()

AUDITS = []
module('apps.access.policy', permitted_management_reviews=lambda user: EvidenceScope())
module('apps.ai_assistant.access', require_ai_access=access)
module('apps.ai_assistant.models', AIToolAudit=types.SimpleNamespace(objects=types.SimpleNamespace(create=lambda **kw: AUDITS.append(kw))))
module('apps.ai_assistant.provider', get_provider=lambda: None, AIProviderError=AIProviderError, Completion=Completion)
module('apps.analytics.services.discovery', list_available_projects=lambda **kwargs: {})
module('apps.ai_assistant.tools')
registry = importlib.import_module('apps.ai_assistant.registry')
CALLS = []

def domain(name, user, **args):
    CALLS.append((name, deepcopy(args)))
    if name == 'lookup_visible_people':
        return {'matches':[{'role':'team_leader','id':LID,'name':'Asim Jamal','match_type':'direct'}]}
    if name == 'find_pending_reviews':
        named = bool(args.get('team_leader_id'))
        leaders = [{'team_leader_id':LID,'name':'Asim Jamal','pending':24,'overdue':16,'submitted_in_period':13}]
        if not named: leaders.insert(0, {'team_leader_id':'id-Ahsan','name':'Ahsan Tanveer','pending':75,'overdue':75,'submitted_in_period':0})
        return {'total_pending':24 if named else 99,'submitted_in_period_pending':(24 if named else 99) if args.get('all_time') else 13,
                'carried_over':0 if args.get('all_time') else (11 if named else 86),
                'overdue_48h':16 if named else 91, 'leaders':leaders,
                'period':dict(args), 'interpretation':args.get('mode','current_backlog'),
                'reports':[{'review_id':rid} for rid in RIDS],
                'completeness':{'aggregate_complete':True}}
    if name in {'rank_teams','rank_agents'}:
        best = args.get('order') == 'best'
        if name == 'rank_teams':
            rows = [{'team_id':'t1','name':'Team Alpha','average_score':95,'critical_error_reviews':1,'evaluations':8,'scored':8},
                    {'team_id':'t2','name':'Team Beta','average_score':65,'critical_error_reviews':3,'evaluations':5,'scored':5}]
            if not best: rows.reverse()
            return {'teams':rows, 'metric':args['metric'],'order':args['order']}
        return {'agents':[{'agent_name':'Haris','agent_user':'8025','dialer_id':'dialer1','critical_error_reviews':3,'evaluations':4,'scored':4,'average_score':80}],
                'metric':args['metric'],'order':args['order']}
    if name == 'list_available_projects': return {'projects':[{'project_name':'Project A'}]}
    if name == 'get_qa_overview': return {'metrics':{'evaluations':172,'critical_error_reviews':75}}
    return {'matches':[], 'repeated_issues':[], 'reviews_with_critical_errors':0}

# Load actual registry argument contracts without importing database services.
env = vars(registry)
for node in ast.parse((ROOT/'backend/apps/ai_assistant/tools.py').read_text()).body:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Call):
        call = node.value.func
        if isinstance(call.func, ast.Name) and call.func.id == 'register':
            values = [eval(compile(ast.Expression(arg), '<tool schema>', 'eval'), env) for arg in call.args]
            name = values[0]
            registry.register(*values)(lambda user, _name=name, **kw: domain(_name,user,**kw))
engine = importlib.import_module('apps.ai_assistant.investigation')

def call(name, args, ident='call'):
    return Completion({'tool_calls':[{'id':ident,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}, 'tool_calls')

def choose(names, **args): return call('select_qa_tools', {'names':names, **args}, 'selection')
class Provider:
    def __init__(self, replies, repeat=False): self.replies, self.index, self.repeat = replies, 0, repeat
    def complete(self, messages, tools):
        self.index += 1
        if self.index <= len(self.replies):
            result = self.replies[self.index-1]
        elif self.repeat: result = self.replies[-1]
        else: result = Completion({'content':'Finished.'})
        if isinstance(result, Exception): raise result
        return result

class EngineContracts(unittest.TestCase):
    def setUp(self): CALLS.clear(); AUDITS.clear()
    def run_turn(self, q, replies, previous=None, repeat=False, **limits):
        p = Provider(replies, repeat)
        conversation = types.SimpleNamespace(context_state=previous) if previous is not None else None
        with patch.object(engine,'get_provider',return_value=p), (patch.multiple(engine, **limits) if limits else nullcontext()):
            result = engine.run_ai('allowed',q,conversation=conversation)
        self.provider = p
        return result

    def test_collective_result_survives_person_lookup_at_round_limit(self):
        r = self.run_turn('Which team leaders have pending QA reports this week?',
                          [choose(['lookup_visible_people','find_pending_reviews']),
                           call('lookup_visible_people', {'search':'Asim Jamal'})], repeat=True, MAX_ROUNDS=2)
        self.assertIn('99',r['answer']); self.assertIn('Ahsan Tanveer',r['answer']); self.assertIn('Asim Jamal',r['answer'])
        self.assertEqual(r['interpretation']['result_status'],'complete')
        self.assertTrue(r['evidence']); self.assertEqual(r['interpretation']['date_from'],'2026-10-05')
        self.assertNotIn('last_person',r['context_state'])
        self.assertNotIn('team_leader_id',next(a for n,a in CALLS if n=='find_pending_reviews'))

    def test_model_narrowing_is_rejected_and_full_backlog_queried(self):
        r = self.run_turn('Which team leaders have pending reports?',
                          [choose(['lookup_visible_people','find_pending_reviews']),
                           call('lookup_visible_people',{'search':'Asim Jamal'}),
                           call('find_pending_reviews',{'team_leader_id':LID}), Completion({'content':'24 pending.'})])
        self.assertIn('99',r['answer'])
        self.assertTrue(all(not a.get('team_leader_id') for n,a in CALLS if n=='find_pending_reviews'))

    def test_named_leader_requires_lookup_and_narrowed_query(self):
        r = self.run_turn('How many reports are pending for Asim Jamal?',
                          [choose(['lookup_visible_people','find_pending_reviews']),
                           call('lookup_visible_people',{'search':'Asim Jamal'}),
                           call('find_pending_reviews', {'team_leader_id':LID}), Completion({'content':'bad 999'})])
        self.assertIn('24',r['answer']); self.assertNotIn('999',r['answer']); self.assertIn('Asim Jamal',r['answer'])
        self.assertEqual([a for n,a in CALLS if n=='find_pending_reviews'][0]['team_leader_id'],LID)

    def test_all_time_no_default_dates(self):
        r=self.run_turn('Which team leaders have pending QA reports for all time?',
                        [choose(['find_pending_reviews']),call('find_pending_reviews',{'date_from':'2023-01-01','date_to':'2023-01-31'})])
        self.assertTrue(r['interpretation']['all_time']); self.assertIsNone(r['interpretation']['date_from'])
        self.assertIn('All-time',r['answer']); self.assertNotIn('last 30',r['answer'])
        a=[a for n,a in CALLS if n=='find_pending_reviews'][0]
        self.assertTrue(a['all_time']); self.assertNotIn('date_from',a)

    def test_wrong_agent_tool_cannot_answer_team_worst(self):
        r=self.run_turn('which team has been performing the worst in the past 10 days',
                        [choose(['rank_agents'],intent='agent_ranking',rank_metric='critical_error_reviews'),
                         call('rank_agents', {'metric':'critical_error_reviews'}), Completion({'content':'Haris is worst'})])
        self.assertIn('Team Beta',r['answer']); self.assertNotIn('Haris',r['answer'])
        self.assertNotIn('rank_agents',[n for n,a in CALLS])
        self.assertEqual(r['interpretation']['subject'],'team')

    def test_new_team_best_does_not_repeat_agent_worst_context(self):
        previous={'last_analysis':{'kind':'agent_ranking','metric':'critical_error_reviews','order':'worst','filters':{}},
                  'time_window':{'date_from':'2026-09-10','date_to':'2026-10-09'}}
        r=self.run_turn('which team has been performing the best in the past 10 days',
                        [choose(['rank_agents'],intent='agent_ranking'),call('rank_agents',{'metric':'critical_error_reviews'}),Completion({'content':'Haris'})],previous)
        self.assertIn('Team Alpha',r['answer']); self.assertNotIn('Haris',r['answer']); self.assertEqual(r['interpretation']['order'],'best')

    def test_team_worst_then_best_use_opposite_directions(self):
        r=self.run_turn('which team performed worst in past 10 days',
                        [choose(['rank_teams']),call('rank_teams',{'metric':'average_score','order':'best'})])
        self.assertIn('Team Beta',r['answer'])
        r2=self.run_turn('and which team is best?',[],r['context_state'])
        self.assertIn('Team Alpha',r2['answer']); self.assertEqual(self.provider.index,0)
        self.assertEqual(r2['interpretation']['date_from'],'2026-09-30')

    def test_explicit_dates_override_model_historical_year(self):
        r=self.run_turn('which team performed best yesterday',
                        [choose(['rank_teams']),call('rank_teams',{'metric':'average_score','order':'worst','date_from':'2023-01-01'})])
        a=[a for n,a in CALLS if n=='rank_teams'][0]
        self.assertEqual((a['date_from'],a['date_to']),('2026-10-08','2026-10-08'))
        self.assertEqual(a['order'],'best')

    def test_social_is_no_db_no_model_and_preserves_context(self):
        previous={'query_contract':{'version':1,'subject':'team','operation':'ranking'},'time_window':{'all_time':True}}
        for q in ('how are you?', 'are you avaialble?', 'hello', 'thank you'):
            with self.subTest(q=q):
                r=self.run_turn(q,[],previous)
                self.assertEqual(self.provider.index,0); self.assertFalse(CALLS)
                self.assertEqual(r['context_state'],previous); self.assertEqual(r['tools_used'],[])
                self.assertEqual(r['interpretation']['response_kind'],'conversation')

    def test_social_plus_business_not_swallowed(self):
        r=self.run_turn('Hello, which team performed best?', [choose(['rank_teams']),call('rank_teams',{'metric':'average_score'})])
        self.assertIn('rank_teams',r['tools_used'])

    def test_unasked_age_filter_cannot_narrow_pending(self):
        r=self.run_turn('Which team leaders have pending reports?',
                        [choose(['find_pending_reviews']),call('find_pending_reviews',{'older_than_days':365})])
        self.assertIn('99',r['answer'])
        self.assertTrue(all(not a.get('older_than_days') for n,a in CALLS if n=='find_pending_reviews'))

    def test_identical_query_replayed_without_repeating_db(self):
        r=self.run_turn('which team performed worst?',[choose(['rank_teams']),call('rank_teams',{'metric':'average_score'})],repeat=True)
        self.assertEqual(sum(n=='rank_teams' for n,a in CALLS),1)
        self.assertEqual(r['interpretation']['result_status'],'complete')

    def test_provider_failure_after_primary_returns_verified_primary(self):
        r=self.run_turn('which team performed best?',[choose(['rank_teams']),call('rank_teams',{'metric':'average_score'}),AIProviderError('unavailable')])
        self.assertIn('Team Alpha',r['answer']); self.assertEqual(r['interpretation']['result_status'],'complete')

    def test_no_time_budget_does_not_claim_last_lookup_is_answer(self):
        r=self.run_turn('which team performed worst?', [choose(['rank_teams'])], MAX_SECONDS=0)
        self.assertEqual(r['interpretation']['result_status'],'incomplete')
        self.assertNotIn('Team Alpha',r['answer']); self.assertNotIn('Team Beta',r['answer'])
        self.assertFalse(r['evidence'])

    def test_scope_suffix_is_never_duplicated(self):
        r=self.run_turn('how many total evaluations?', [choose(['get_qa_overview']),call('get_qa_overview',{}),Completion({'content':'Results are limited to your authorized QA records.'})])
        self.assertEqual(r['answer'].count('Results are limited'),1)

    def test_scoped_discovery_cannot_silently_set_collective_person(self):
        r=self.run_turn('which team leaders have pending reports this week?', [choose(['lookup_visible_people']),call('lookup_visible_people',{'search':'Asim Jamal'})])
        self.assertTrue(r['context_state']['query_contract']['collection'])
        self.assertNotIn('team_leader_id',r['context_state']['query_contract']['filters'])

    def test_unapproved_tool_not_executed(self):
        r=self.run_turn('which team performed best?', [choose(['rank_teams']),call('execute_sql',{'sql':'DROP TABLE'})])
        self.assertNotIn('execute_sql',[n for n,a in CALLS]); self.assertIn('Team Alpha',r['answer'])

    def test_compaction_does_not_mutate_raw_results(self):
        d={'leaders':[{'name':str(i)} for i in range(30)],'warnings':[],'total_pending':500}
        before=deepcopy(d); compact=engine._bounded_data(d)
        self.assertEqual(d,before); self.assertEqual(compact['total_pending'],500); self.assertLess(len(compact['leaders']),30)

    def test_semantic_personal_mode_has_no_qa_queries(self):
        prior={'query_contract':{'version':1,'subject':'team','operation':'ranking'}, 'time_window':{'all_time':True}}
        selected=call('select_qa_tools', {'names':[], 'request_kind':'conversation', 'social_topic':'personal'})
        r=self.run_turn('Does software like you ever need a break?', [selected], prior)
        self.assertEqual(self.provider.index,1)
        self.assertFalse(CALLS); self.assertFalse(r['tools_used'])
        self.assertEqual(r['interpretation']['response_kind'],'conversation')
        self.assertEqual(r['context_state'],prior)

    def test_model_cannot_bypass_business_query_with_social_mode(self):
        selected=call('select_qa_tools', {'names':[], 'request_kind':'conversation', 'social_topic':'thanks'})
        r=self.run_turn('Hello, which team performed best?', [selected, Completion({'content':'You are welcome'})])
        self.assertIn('Team Alpha',r['answer']); self.assertIn('rank_teams',r['tools_used'])

    def test_malformed_prior_cursor_is_bounded(self):
        first=self.run_turn('Which team performed best?', [choose(['rank_teams']),call('rank_teams',{'metric':'average_score'})])
        first['context_state']['query_contract']['rank_cursor']={'unexpected':'object'}
        r=self.run_turn("and who's next?",[],first['context_state'])
        self.assertIn('Team Beta',r['answer'])

    def test_invalid_extra_primary_parameters_not_silently_accepted(self):
        r=self.run_turn('Which team leaders have pending reports?', [choose(['find_pending_reviews']),
                        call('find_pending_reviews',{'role':'administrator'}),Completion({'content':'done'})])
        self.assertIn('99',r['answer'])
        self.assertTrue(all('role' not in args for name,args in CALLS if name=='find_pending_reviews'))

    def test_verified_primary_stops_supplementary_person_lookup(self):
        r=self.run_turn('Which team leaders have pending reports?', [choose(['find_pending_reviews','lookup_visible_people']),
                        call('find_pending_reviews',{}),call('lookup_visible_people',{'search':'Asim Jamal'})])
        self.assertIn('Ahsan Tanveer',r['answer']); self.assertIn('Asim Jamal',r['answer'])
        self.assertFalse(any(n=='lookup_visible_people' for n,a in CALLS))
        self.assertEqual(r['interpretation']['result_status'],'complete')

    def test_unsupported_summary_replacement_is_observable(self):
        r=self.run_turn('How many reports are pending for Asim Jamal?', [choose(['lookup_visible_people','find_pending_reviews']),
                        call('lookup_visible_people',{'search':'Asim Jamal'}),call('find_pending_reviews',{'team_leader_id':LID}),
                        Completion({'content':'999 pending reports'})])
        self.assertIn('24 pending',r['answer'])
        self.assertIn('replaced',r['warnings'][0])

if __name__=='__main__':
    # Re-run existing pure regression classes against the same actual helpers,
    # without pretending these are ORM tests. No source expectations are edited.
    names = {'V3CalendarAndToolsTests', 'V3ContextAndConversationTests',
             'V3RankingSemanticsTests', 'V3TypedSemanticSelectionTests'}
    source = ast.parse((ROOT/'backend/apps/ai_assistant/tests.py').read_text())
    pure_classes = [node for node in source.body if isinstance(node, ast.ClassDef) and node.name in names]
    namespace = {'__package__':'apps.ai_assistant', '__name__':'offline_existing_contracts',
                 'SimpleTestCase':unittest.TestCase, 'json':json}
    exec(compile(ast.Module(body=pure_classes, type_ignores=[]), 'existing_pure_contracts', 'exec'), namespace)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EngineContracts)
    for name in sorted(names):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[name]))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if outcome.wasSuccessful() else 1)
