import { DeleteOutlined, FilterOutlined, PlusOutlined } from '@ant-design/icons';
import { Button, Collapse, DatePicker, Drawer, InputNumber, Segmented, Select, Space, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { appCalendarDate, appDate } from '../lib/datetime';
import type { QAReportSummary, QAScorecard } from '../types';

const { Text, Title } = Typography;
const { RangePicker } = DatePicker;

export type ScoreRuleScope = 'total' | 'category' | 'criterion';
export type ScoreRuleOperator = 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq' | 'between' | 'outside';

export interface TeamLeaderScoreRule {
  id: string;
  scope: ScoreRuleScope;
  key: string;
  operator: ScoreRuleOperator;
  value: number | null;
  valueTo: number | null;
  unit: 'points' | 'percent';
}

export interface TeamLeaderReportFilterValue {
  projects: string[];
  reviewers: string[];
  teamLeaders: string[];
  teams: string[];
  agents: string[];
  dispositions: string[];
  directions: string[];
  ratings: string[];
  qaStatuses: string[];
  workflowStatuses: string[];
  evaluationTypes: string[];
  coverageTiers: string[];
  critical: 'any' | 'true' | 'false';
  scoreState: 'all' | 'scored' | 'unscored';
  overdue: 'any' | 'true' | 'false';
  leaderActivity: 'all' | 'with_activity' | 'without_activity';
  dateField: 'assigned_at' | 'completed_at' | 'call_date' | 'leader_updated_at';
  dateRange: [string, string] | null;
  scoreMatch: 'all' | 'any';
  scoreRules: TeamLeaderScoreRule[];
}

export const EMPTY_TEAM_LEADER_FILTERS: TeamLeaderReportFilterValue = {
  projects: [], reviewers: [], teamLeaders: [], teams: [], agents: [], dispositions: [], directions: [], ratings: [],
  qaStatuses: [], workflowStatuses: [], evaluationTypes: [], coverageTiers: [], critical: 'any', scoreState: 'all',
  overdue: 'any', leaderActivity: 'all', dateField: 'completed_at', dateRange: null, scoreMatch: 'all', scoreRules: [],
};

export function teamLeaderFilterCount(value: TeamLeaderReportFilterValue) {
  return value.projects.length + value.reviewers.length + value.teamLeaders.length + value.teams.length + value.agents.length
    + value.dispositions.length + value.directions.length + value.ratings.length + value.qaStatuses.length
    + value.workflowStatuses.length + value.evaluationTypes.length + value.coverageTiers.length
    + (value.critical === 'any' ? 0 : 1) + (value.scoreState === 'all' ? 0 : 1)
    + (value.overdue === 'any' ? 0 : 1) + (value.leaderActivity === 'all' ? 0 : 1)
    + (value.dateRange ? 1 : 0) + value.scoreRules.length;
}

function regularFilterCount(value: TeamLeaderReportFilterValue) {
  return teamLeaderFilterCount(value) - value.scoreRules.length;
}

const OPERATORS: Array<{ value: ScoreRuleOperator; label: string }> = [
  { value: 'gt', label: 'Greater than' }, { value: 'gte', label: 'At least' },
  { value: 'lt', label: 'Less than' }, { value: 'lte', label: 'At most' },
  { value: 'eq', label: 'Equal to' }, { value: 'neq', label: 'Not equal to' },
  { value: 'between', label: 'Between' }, { value: 'outside', label: 'Outside range' },
];

const RATINGS = [
  ['not_evaluable', 'Not Evaluable'],
  ['excellent', 'Excellent'], ['very_good', 'Very Good'], ['good', 'Good'],
  ['needs_improvement', 'Needs Improvement'], ['unsatisfactory', 'Unsatisfactory'], ['automatic_fail', 'Automatic Fail'],
].map(([value, label]) => ({ value, label }));

const WORKFLOWS = [
  ['pending', 'Needs review'], ['acknowledged', 'Reviewed'], ['coaching_planned', 'Coaching planned'],
  ['coaching_completed', 'Coaching completed'], ['escalated', 'Escalated'], ['returned_to_qa', 'Returned to QA'], ['closed', 'Closed'],
].map(([value, label]) => ({ value, label }));

const QA_STATUSES = [
  ['assigned', 'Assigned'], ['in_progress', 'In progress'], ['revision_required', 'Revision required'],
  ['completed', 'Completed'], ['disputed', 'Disputed'],
].map(([value, label]) => ({ value, label }));

const EVALUATION_TYPES = [
  ['full', 'Full call'], ['partial', 'Partial call'], ['not_evaluable', 'Not evaluable'], ['agent_premature', 'Agent ended early'],
].map(([value, label]) => ({ value, label }));

const COVERAGE_TIERS = [
  ['insufficient', 'Insufficient'], ['limited', 'Limited'], ['partial', 'Partial'], ['full', 'Full'],
].map(([value, label]) => ({ value, label }));

function newRule(): TeamLeaderScoreRule {
  return { id: `${Date.now()}-${Math.random()}`, scope: 'total', key: 'total', operator: 'lt', value: 85, valueTo: null, unit: 'points' };
}

function cloneFilters(value: TeamLeaderReportFilterValue): TeamLeaderReportFilterValue {
  return { ...value, dateRange: value.dateRange ? [...value.dateRange] : null, scoreRules: value.scoreRules.map((rule) => ({ ...rule })) };
}

function scoreTargets(scorecard?: QAScorecard) {
  return [
    { label: 'Report', options: [{ value: 'total:total', label: 'Total score', maxScore: 100 }] },
    { label: 'Headings', options: (scorecard?.categories ?? []).map((category) => ({ value: `category:${category.key}`, label: category.label, maxScore: category.max_score })) },
    { label: 'Subheadings', options: (scorecard?.categories ?? []).flatMap((category) => category.criteria.map((criterion) => ({ value: `criterion:${criterion.key}`, label: `${category.label} · ${criterion.label}`, maxScore: criterion.max_score }))) },
  ];
}

function multiOptions(values: string[]) { return values.map((value) => ({ value, label: value })); }

interface Props {
  open: boolean;
  value: TeamLeaderReportFilterValue;
  options?: QAReportSummary['filters'];
  oversight?: boolean;
  onClose: () => void;
  onApply: (value: TeamLeaderReportFilterValue) => void;
}

export function TeamLeaderReportFilters({ open, value, options, oversight = false, onClose, onApply }: Props) {
  const [draft, setDraft] = useState(() => cloneFilters(value));
  const [panel, setPanel] = useState<'filters' | 'scores'>('filters');
  useEffect(() => {
    if (!open) return undefined;
    const timer = window.setTimeout(() => {
      setDraft(cloneFilters(value));
      setPanel('filters');
    }, 0);
    return () => window.clearTimeout(timer);
  }, [open, value]);
  const targets = useMemo(() => scoreTargets(options?.scorecard), [options?.scorecard]);
  const rawTargetMaximum = (rule: TeamLeaderScoreRule) => targets.flatMap((group) => group.options).find((item) => item.value === `${rule.scope}:${rule.key}`)?.maxScore ?? 100;
  const targetMaximum = (rule: TeamLeaderScoreRule) => rule.unit === 'percent' ? 100 : rawTargetMaximum(rule);
  const update = <K extends keyof TeamLeaderReportFilterValue>(key: K, next: TeamLeaderReportFilterValue[K]) => setDraft((current) => ({ ...current, [key]: next }));
  const updateRule = (id: string, patch: Partial<TeamLeaderScoreRule>) => update('scoreRules', draft.scoreRules.map((rule) => rule.id === id ? { ...rule, ...patch } : rule));
  const invalidRules = draft.scoreRules.some((rule) => rule.value === null || (['between', 'outside'].includes(rule.operator) && rule.valueTo === null));
  const addRule = () => { update('scoreRules', [...draft.scoreRules, newRule()]); setPanel('scores'); };

  const mainFilters = <div className="tl-filter-grid">
    <label><span>Project</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any project" value={draft.projects} onChange={(next) => update('projects', next)} options={multiOptions(options?.projects ?? [])} /></label>
    <label><span>QA analyst</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any analyst" value={draft.reviewers} onChange={(next) => update('reviewers', next)} options={(options?.reviewers ?? []).map((item) => ({ value: item.reviewer_id, label: `${item.reviewer__first_name} ${item.reviewer__last_name}`.trim() }))} /></label>
    {oversight && <label><span>QA stage</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any stage" value={draft.qaStatuses} onChange={(next) => update('qaStatuses', next)} options={QA_STATUSES} /></label>}
    {oversight && <label><span>Team Leader</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any leader" value={draft.teamLeaders} onChange={(next) => update('teamLeaders', next)} options={(options?.team_leaders ?? []).map((item) => ({ value: item.team_leader_id, label: `${item.team_leader__first_name} ${item.team_leader__last_name}`.trim() }))} /></label>}
    <label><span>Agent</span><Select mode="multiple" showSearch={{ optionFilterProp: 'label' }} maxTagCount="responsive" allowClear placeholder="Any agent" value={draft.agents} onChange={(next) => update('agents', next)} options={multiOptions(options?.agents ?? [])} /></label>
    <label><span>Result</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any result" value={draft.ratings} onChange={(next) => update('ratings', next)} options={RATINGS} /></label>
    <label><span>Workflow</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any status" value={draft.workflowStatuses} onChange={(next) => update('workflowStatuses', next)} options={WORKFLOWS} /></label>
    <label><span>Date</span><RangePicker value={draft.dateRange ? [appCalendarDate(draft.dateRange[0]), appCalendarDate(draft.dateRange[1])] : null} presets={[{ label: 'Last 7 days', value: [appDate().subtract(6, 'day'), appDate()] }, { label: 'Last 30 days', value: [appDate().subtract(29, 'day'), appDate()] }, { label: 'This month', value: [appDate().startOf('month'), appDate()] }]} onChange={(dates) => update('dateRange', dates ? [dates[0]!.format('YYYY-MM-DD'), dates[1]!.format('YYYY-MM-DD')] : null)} /></label>
  </div>;

  const moreFilters = <div className="tl-filter-grid">
    <label><span>Team</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any team" value={draft.teams} onChange={(next) => update('teams', next)} options={multiOptions(options?.teams ?? [])} /></label>
    <label><span>Call direction</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any direction" value={draft.directions} onChange={(next) => update('directions', next)} options={multiOptions(options?.directions ?? [])} /></label>
    <label><span>Disposition</span><Select mode="multiple" showSearch={{ optionFilterProp: 'label' }} maxTagCount="responsive" allowClear placeholder="Any disposition" value={draft.dispositions} onChange={(next) => update('dispositions', next)} options={multiOptions(options?.dispositions ?? [])} /></label>
    <label><span>Critical violation</span><Segmented block value={draft.critical} onChange={(next) => update('critical', next as TeamLeaderReportFilterValue['critical'])} options={[{ value: 'any', label: 'Any' }, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} /></label>
    <label><span>Score status</span><Select value={draft.scoreState} onChange={(next) => update('scoreState', next)} options={[{ value: 'all', label: 'Any' }, { value: 'scored', label: 'Scored' }, { value: 'unscored', label: 'Scorecard waived' }]} /></label>
    <label><span>Evaluation type</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any type" value={draft.evaluationTypes} onChange={(next) => update('evaluationTypes', next)} options={EVALUATION_TYPES} /></label>
    <label><span>Coverage tier</span><Select mode="multiple" maxTagCount="responsive" allowClear placeholder="Any coverage" value={draft.coverageTiers} onChange={(next) => update('coverageTiers', next)} options={COVERAGE_TIERS} /></label>
    <label><span>Coaching overdue</span><Segmented block value={draft.overdue} onChange={(next) => update('overdue', next as TeamLeaderReportFilterValue['overdue'])} options={[{ value: 'any', label: 'Any' }, { value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} /></label>
    <label><span>Team Leader activity</span><Select value={draft.leaderActivity} onChange={(next) => update('leaderActivity', next)} options={[{ value: 'all', label: 'Any' }, { value: 'with_activity', label: 'Has activity' }, { value: 'without_activity', label: 'No activity' }]} /></label>
    <label><span>Date uses</span><Select value={draft.dateField} onChange={(next) => update('dateField', next)} options={[{ value: 'assigned_at', label: 'QA assignment date' }, { value: 'completed_at', label: 'QA submission date' }, { value: 'leader_updated_at', label: 'Team Leader activity date' }, { value: 'call_date', label: 'Call date' }]} /></label>
  </div>;

  const scoreFilters = draft.scoreRules.length === 0
    ? <div className="tl-score-query-empty"><strong>No score filters</strong><Button type="primary" icon={<PlusOutlined />} onClick={addRule}>Add score filter</Button></div>
    : <div className="tl-score-rule-list">
      {draft.scoreRules.length > 1 && <div className="tl-score-match"><Text>Reports must match</Text><Segmented size="small" value={draft.scoreMatch} onChange={(next) => update('scoreMatch', next as 'all' | 'any')} options={[{ value: 'all', label: 'All conditions' }, { value: 'any', label: 'Any condition' }]} /></div>}
      {draft.scoreRules.map((rule) => {
        const range = ['between', 'outside'].includes(rule.operator);
        const maximum = targetMaximum(rule);
        return <div className="tl-score-rule" key={rule.id}><div className="tl-score-rule__controls">
          <label><span>Score</span><Select showSearch={{ optionFilterProp: 'label' }} value={`${rule.scope}:${rule.key}`} onChange={(next: string) => { const [scope, key] = next.split(':') as [ScoreRuleScope, string]; updateRule(rule.id, { scope, key, value: null, valueTo: null }); }} options={targets} /></label>
          <label><span>Condition</span><Select value={rule.operator} onChange={(operator) => updateRule(rule.id, { operator, valueTo: ['between', 'outside'].includes(operator) ? rule.valueTo : null })} options={OPERATORS} /></label>
          <label><span>Value</span><div className="tl-score-rule__values"><InputNumber min={0} max={maximum} precision={2} controls={false} placeholder="0" value={rule.value} onChange={(next) => updateRule(rule.id, { value: next })} />{range && <><span>to</span><InputNumber min={0} max={maximum} precision={2} controls={false} placeholder="0" value={rule.valueTo} onChange={(next) => updateRule(rule.id, { valueTo: next })} /></>}</div></label>
          <label><span>Unit</span><Select value={rule.unit} onChange={(unit) => updateRule(rule.id, { unit, value: null, valueTo: null })} options={[{ value: 'points', label: `Points · max ${rawTargetMaximum(rule)}` }, { value: 'percent', label: 'Percent' }]} /></label>
        </div><Button type="text" danger shape="circle" icon={<DeleteOutlined />} aria-label="Remove score filter" onClick={() => update('scoreRules', draft.scoreRules.filter((item) => item.id !== rule.id))} /></div>;
      })}
      <Button type="dashed" icon={<PlusOutlined />} disabled={draft.scoreRules.length >= 12} onClick={addRule}>Add condition</Button>
      {invalidRules && <Text type="danger">Complete each score filter before applying.</Text>}
    </div>;

  return <Drawer open={open} onClose={onClose} size="min(720px, calc(100vw - 16px))" classNames={{ body: 'tl-advanced-filter__body' }} title={<div className="tl-filter-drawer-title"><FilterOutlined /><Title level={5}>Filter reports</Title></div>} footer={<div className="tl-filter-drawer-footer"><Button disabled={!teamLeaderFilterCount(draft)} onClick={() => setDraft(cloneFilters(EMPTY_TEAM_LEADER_FILTERS))}>Clear</Button><Space><Button onClick={onClose}>Cancel</Button><Button type="primary" disabled={invalidRules} onClick={() => onApply(cloneFilters(draft))}>Apply</Button></Space></div>}>
    <div className="tl-advanced-filter">
      <Segmented block value={panel} onChange={(next) => setPanel(next as 'filters' | 'scores')} options={[{ value: 'filters', label: `Filters${regularFilterCount(draft) ? ` · ${regularFilterCount(draft)}` : ''}` }, { value: 'scores', label: `Scores${draft.scoreRules.length ? ` · ${draft.scoreRules.length}` : ''}` }]} />
      {panel === 'filters' ? <div className="tl-filter-panel-content">{mainFilters}<Collapse ghost size="small" expandIconPlacement="end" items={[{ key: 'more', label: 'More filters', children: moreFilters }]} /></div> : <div className="tl-filter-panel-content">{scoreFilters}</div>}
    </div>
  </Drawer>;
}
