"""Offline contract smoke checks, no Django install or database required.

These are NOT Django integration tests. Use manage.py test before deploying.
"""
import ast
import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import Mock

HERE = Path(__file__).resolve().parents[1]
COUNT = 0

def check(condition, label):
    global COUNT
    if not condition:
        raise AssertionError(label)
    COUNT += 1
    print('PASS:', label)

files = list((HERE/'apps').rglob('*.py'))
for f in files:
    ast.parse(f.read_text())
check(len(files) > 100, 'all Django app modules parse')

services = HERE/'apps/analytics/services'
names = set()
for f in services.glob('*.py'):
    tree = ast.parse(f.read_text())
    names.update(n.name for n in tree.body if isinstance(n,ast.FunctionDef))
registry = ast.parse((HERE/'apps/ai_assistant/tools.py').read_text())
registered = [node for node in registry.body if isinstance(node, ast.Expr) and
              isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Call) and
              isinstance(node.value.func.func,ast.Name) and node.value.func.func.id == 'register']
check(len(registered)==24, '24 tool declarations preserved')
registered_names = [node.value.func.args[0].value for node in registered]
check(len(registered_names)==len(set(registered_names)), 'tool names unique')
check(all(name in names for name in registered_names), 'tool handlers exist in domain services')
check('from apps.access.report_scope import scoped_reports, _report_base_queryset' in
      (HERE/'apps/calls/views.py').read_text(), 'legacy report views use shared authoritative scope')
check('from apps.access.report_scope import scoped_reports' in
      (HERE/'apps/dashboard/views.py').read_text(), 'dashboard uses shared scope')
check('all_time=True' in (services/'reviews.py').read_text(), 'backlog includes old pending work')
check('context_state' in (HERE/'apps/ai_assistant/migrations/0003_semantic_state.py').read_text(),
      'semantic state migration exists')
check('AI_ENGINE_VERSION' in (HERE/'config/settings.py').read_text(), 'safe V1/V2 rollback switch')
check('render_analytics' in (HERE/'apps/ai_assistant/orchestrator.py').read_text(),
      'deterministic metric answer validator wired')
check('AIInsightsPage' not in (HERE/'apps/ai_assistant/tools.py').read_text(),
      'backend tools independent of UI')

# Import the pure-Python semantic plan in a stubbed offline environment.
django=types.ModuleType('django'); util=types.ModuleType('django.utils')
utimezone=types.ModuleType('django.utils.timezone'); utimezone.localdate=lambda: date(2026,10,9)
django.utils=util; util.timezone=utimezone
rest=types.ModuleType('rest_framework'); rest_exc=types.ModuleType('rest_framework.exceptions')
class ValidationError(Exception): pass
rest_exc.ValidationError=ValidationError
sys.modules.update({'django':django,'django.utils':util,'django.utils.timezone':utimezone,
                    'rest_framework':rest,'rest_framework.exceptions':rest_exc})
imported_name='offline_ai_planning'
spec=importlib.util.spec_from_file_location(imported_name,HERE/'apps/ai_assistant/planning.py')
mod=importlib.util.module_from_spec(spec);sys.modules[imported_name]=mod;spec.loader.exec_module(mod)
plan=mod._fallback('Which TLs have pending reports this week?')
check(plan.intent=='review_backlog' and plan.backlog_mode=='current_backlog',
      'loose question defaults to current backlog')
check(plan.dates()==('2026-10-05','2026-10-09'), 'week dates deterministic')
check(mod._fallback('Who made the same mistake again?').intent=='recurring_mistakes',
      'casual recurrence synonym')
try:
    mod._validated({'intent':'review_backlog','period':'this_week','role':'administrator'})
except ValidationError:
    check(True, 'model cannot inject role in typed plan')
else:
    check(False, 'model cannot inject role in typed plan')
provider=Mock()
provider.complete.return_value=types.SimpleNamespace(message={'tool_calls':[{
 'type':'function','id':'c1','function':{'name':'submit_query_plan',
 'arguments':json.dumps({'intent':'review_backlog','period':'this_week',
                          'company_name':'Mars','branch_name':'Arena'})}}]})
structured=mod.plan_question(provider,'Which TLs in Mars Arena have pending work this week?')
check(structured.company_name=='Mars' and structured.branch_name=='Arena',
      'typed model plan accepts explicit company and branch name hints')
print(f'OFFLINE CONTRACT CHECKS: {COUNT}/{COUNT} passed (not a Django runtime test)')
