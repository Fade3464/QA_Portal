import {
  ArrowRightOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  FileDoneOutlined,
  FilterOutlined,
  PlayCircleOutlined,
  SearchOutlined,
  SendOutlined,
  WarningFilled,
} from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Avatar,
  Badge,
  Button,
  Card,
  Collapse,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Input,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
  type TableProps,
} from 'antd';
import type { Dayjs } from 'dayjs';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { AudioPlayer, type AudioRangeRequest } from '../components/AudioPlayerModal';
import { formatEvidenceTime } from '../components/CriterionEvidenceEditor';
import { ContentLoader } from '../components/LoadingStates';
import {
  EMPTY_TEAM_LEADER_FILTERS,
  TeamLeaderReportFilters,
  teamLeaderFilterCount,
  type TeamLeaderReportFilterValue,
} from '../components/TeamLeaderReportFilters';
import { api, ApiError } from '../lib/api';
import type {
  PaginatedResponse,
  QAReport,
  QAReportDetail,
  QAReportSummary,
  QAScorecard,
  QACriterionEvidence,
  QAEvidencePatch,
  TeamLeaderReportStatus,
} from '../types';

const { Paragraph, Text, Title } = Typography;
const { TextArea, Search } = Input;

type ReportSegment = 'all' | 'attention' | 'critical' | 'coaching' | 'closed';

const WORKFLOW_COLORS: Record<TeamLeaderReportStatus, string> = {
  pending: 'warning',
  acknowledged: 'processing',
  coaching_planned: 'purple',
  coaching_completed: 'cyan',
  escalated: 'error',
  returned_to_qa: 'orange',
  closed: 'success',
};

const NEXT_ACTIONS: Record<TeamLeaderReportStatus, TeamLeaderReportStatus[]> = {
  pending: ['acknowledged', 'coaching_planned', 'escalated', 'returned_to_qa'],
  acknowledged: ['coaching_planned', 'escalated', 'closed', 'returned_to_qa'],
  coaching_planned: ['coaching_completed', 'escalated', 'returned_to_qa'],
  coaching_completed: ['coaching_planned', 'closed', 'returned_to_qa'],
  escalated: ['coaching_planned', 'closed', 'returned_to_qa'],
  returned_to_qa: [],
  closed: ['acknowledged', 'returned_to_qa'],
};

const WORKFLOW_LABELS: Record<TeamLeaderReportStatus, string> = {
  pending: 'Needs review',
  acknowledged: 'Reviewed',
  coaching_planned: 'Plan coaching',
  coaching_completed: 'Coaching completed',
  escalated: 'Escalate',
  returned_to_qa: 'Return to QA',
  closed: 'Close report',
};

function outcomeColor(report: QAReport) {
  if (report.critical_errors.length) return 'error';
  const score = Number(report.score ?? 0);
  if (score >= 90) return 'success';
  if (score >= 85) return 'processing';
  return 'warning';
}

function initials(name: string) {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'A';
}

function isOverdue(report: QAReport) {
  return report.leader_status === 'coaching_planned'
    && Boolean(report.coaching_due_at)
    && dayjs(report.coaching_due_at).isBefore(dayjs());
}

export function ReportsPage() {
  const { user } = useAuth();
  if (user?.role === 'team_leader') return <TeamLeaderReports />;
  return <BasicReports />;
}

function TeamLeaderReports() {
  const { message } = AntApp.useApp();
  const [summary, setSummary] = useState<QAReportSummary | null>(null);
  const [reports, setReports] = useState<QAReport[]>([]);
  const [selected, setSelected] = useState<QAReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [savingAction, setSavingAction] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [segment, setSegment] = useState<ReportSegment>('attention');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [reportFilters, setReportFilters] = useState<TeamLeaderReportFilterValue>(EMPTY_TEAM_LEADER_FILTERS);
  const [ordering, setOrdering] = useState('-completed_at');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [actionStatus, setActionStatus] = useState<TeamLeaderReportStatus>();
  const [actionNote, setActionNote] = useState('');
  const [coachingDue, setCoachingDue] = useState<Dayjs | null>(null);
  const [rangeRequest, setRangeRequest] = useState<AudioRangeRequest | null>(null);

  const loadSummary = useCallback(async () => {
    try {
      setSummary(await api<QAReportSummary>('/api/v1/calls/reports/summary/'));
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : 'Report metrics could not be loaded.');
    }
  }, []);

  useEffect(() => {
    let active = true;
    api<QAReportSummary>('/api/v1/calls/reports/summary/')
      .then((data) => { if (active) setSummary(data); })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof ApiError ? requestError.message : 'Report metrics could not be loaded.');
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) setLoading(true); });
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), segment, ordering });
    if (search) params.set('search', search);
    const appendMany = (name: string, values: string[]) => values.forEach((value) => params.append(name, value));
    appendMany('project', reportFilters.projects);
    appendMany('reviewer', reportFilters.reviewers);
    appendMany('team', reportFilters.teams);
    appendMany('agent', reportFilters.agents);
    appendMany('disposition', reportFilters.dispositions);
    appendMany('direction', reportFilters.directions);
    appendMany('rating', reportFilters.ratings);
    appendMany('workflow_status', reportFilters.workflowStatuses);
    if (reportFilters.critical !== 'any') params.set('critical', reportFilters.critical);
    if (reportFilters.scoreState !== 'all') params.set('score_state', reportFilters.scoreState);
    if (reportFilters.dateRange) {
      params.set('date_field', reportFilters.dateField);
      params.set('date_from', reportFilters.dateRange[0]);
      params.set('date_to', reportFilters.dateRange[1]);
    }
    if (reportFilters.scoreRules.length) {
      params.set('score_match', reportFilters.scoreMatch);
      params.set('score_rules', JSON.stringify(reportFilters.scoreRules.map(({ id: _id, valueTo, ...rule }) => ({ ...rule, value_to: valueTo }))));
    }
    api<PaginatedResponse<QAReport>>(`/api/v1/calls/reports/?${params.toString()}`)
      .then((data) => {
        if (!active) return;
        setReports(data.results);
        setTotal(data.count);
        setError('');
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof ApiError ? requestError.message : 'QA reports could not be loaded.');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [ordering, page, pageSize, reportFilters, search, segment]);

  const openReport = async (report: QAReport) => {
    setDetailLoading(true);
    setSelected(null);
    setActionStatus(undefined);
    setActionNote('');
    setCoachingDue(null);
    try {
      setSelected(await api<QAReportDetail>(`/api/v1/calls/reports/${report.id}/`));
    } catch (requestError) {
      void message.error(requestError instanceof Error ? requestError.message : 'The report could not be opened.');
    } finally {
      setDetailLoading(false);
    }
  };

  const submitAction = async () => {
    if (!selected) return;
    if (!actionStatus && !actionNote.trim()) { void message.warning('Choose an action or enter a management note.'); return; }
    if (actionStatus === 'coaching_planned' && !coachingDue) { void message.warning('Choose a coaching deadline.'); return; }
    if (actionStatus === 'returned_to_qa' && !actionNote.trim()) { void message.warning('Explain what the QA analyst needs to reassess.'); return; }
    setSavingAction(true);
    try {
      const updated = await api<QAReportDetail>(`/api/v1/calls/reports/${selected.id}/actions/`, {
        method: 'POST',
        body: JSON.stringify({ leader_status: actionStatus, note: actionNote, coaching_due_at: coachingDue?.toISOString() }),
      });
      const returnedToQa = updated.status === 'revision_required';
      setSelected(returnedToQa ? null : updated);
      setReports((current) => returnedToQa ? current.filter((report) => report.id !== updated.id) : current.map((report) => report.id === updated.id ? updated : report));
      if (returnedToQa) setTotal((current) => Math.max(0, current - 1));
      setActionStatus(undefined);
      setActionNote('');
      setCoachingDue(null);
      void loadSummary();
      void message.success(returnedToQa ? 'Report returned to the QA analyst for reassessment.' : 'Report workflow updated.');
    } catch (requestError) {
      void message.error(requestError instanceof Error ? requestError.message : 'The report could not be updated.');
    } finally {
      setSavingAction(false);
    }
  };

  const clearAllReportFilters = () => { setReportFilters(EMPTY_TEAM_LEADER_FILTERS); setPage(1); };
  const clearFilterGroup = (key: keyof TeamLeaderReportFilterValue) => {
    setReportFilters((current) => ({ ...current, [key]: EMPTY_TEAM_LEADER_FILTERS[key] }));
    setPage(1);
  };

  const columns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="tl-agent"><Avatar size={34}>{initials(row.agent_name || row.agent_user)}</Avatar><span><strong>{row.agent_name || row.agent_user}</strong><small>{row.team_name || 'Unassigned team'}</small></span></div> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => <Text>{value || 'Unmapped'}</Text> },
    { title: 'Score', key: 'score', width: 138, align: 'center', render: (_, row) => <div className="tl-score-cell"><strong>{row.critical_errors.length ? 'FAIL' : `${row.score}%`}</strong><small>{row.critical_errors.length ? 'Critical error' : row.rating_label}</small></div> },
    { title: 'Workflow', key: 'workflow', width: 190, render: (_, row) => <div className="tl-workflow-cell"><Tag color={WORKFLOW_COLORS[row.leader_status]} variant="filled">{row.leader_status_label}</Tag>{isOverdue(row) && <small className="is-overdue"><ClockCircleOutlined /> Overdue</small>}{row.coaching_due_at && !isOverdue(row) && row.leader_status === 'coaching_planned' && <small>Due {dayjs(row.coaching_due_at).format('DD MMM')}</small>}</div> },
    { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer', width: 160 },
    { title: 'Submitted', key: 'completed', width: 150, render: (_, row) => row.completed_at ? <span className="tl-date"><strong>{dayjs(row.completed_at).format('DD MMM YYYY')}</strong><small>{dayjs(row.completed_at).format('h:mm A')}</small></span> : '—' },
    { title: '', key: 'action', width: 58, align: 'center', render: (_, row) => <Button type="text" shape="circle" icon={<ArrowRightOutlined />} aria-label={`Review ${row.agent_name}`} onClick={(event) => { event.stopPropagation(); void openReport(row); }} /> },
  ];

  const advancedFilterCount = teamLeaderFilterCount(reportFilters);
  const summarize = (label: string, values: string[]) => `${label}: ${values[0]}${values.length > 1 ? ` +${values.length - 1}` : ''}`;
  const reviewerNames = reportFilters.reviewers.map((id) => {
    const reviewerOption = summary?.filters.reviewers.find((item) => item.reviewer_id === id);
    return reviewerOption ? `${reviewerOption.reviewer__first_name} ${reviewerOption.reviewer__last_name}`.trim() : 'QA analyst';
  });
  const appliedFilterChips: Array<{ key: keyof TeamLeaderReportFilterValue; label: string }> = [];
  if (reportFilters.projects.length) appliedFilterChips.push({ key: 'projects', label: summarize('Project', reportFilters.projects) });
  if (reviewerNames.length) appliedFilterChips.push({ key: 'reviewers', label: summarize('QA', reviewerNames) });
  if (reportFilters.agents.length) appliedFilterChips.push({ key: 'agents', label: summarize('Agent', reportFilters.agents) });
  if (reportFilters.teams.length) appliedFilterChips.push({ key: 'teams', label: summarize('Team', reportFilters.teams) });
  if (reportFilters.ratings.length) appliedFilterChips.push({ key: 'ratings', label: summarize('Result', reportFilters.ratings.map((value) => value.replaceAll('_', ' '))) });
  if (reportFilters.workflowStatuses.length) appliedFilterChips.push({ key: 'workflowStatuses', label: summarize('Workflow', reportFilters.workflowStatuses.map((value) => value.replaceAll('_', ' '))) });
  if (reportFilters.directions.length) appliedFilterChips.push({ key: 'directions', label: summarize('Direction', reportFilters.directions) });
  if (reportFilters.dispositions.length) appliedFilterChips.push({ key: 'dispositions', label: summarize('Disposition', reportFilters.dispositions) });
  if (reportFilters.critical !== 'any') appliedFilterChips.push({ key: 'critical', label: `Critical: ${reportFilters.critical === 'true' ? 'Yes' : 'No'}` });
  if (reportFilters.scoreState !== 'all') appliedFilterChips.push({ key: 'scoreState', label: reportFilters.scoreState === 'scored' ? 'Scored' : 'Scorecard waived' });
  if (reportFilters.dateRange) appliedFilterChips.push({ key: 'dateRange', label: `${dayjs(reportFilters.dateRange[0]).format('DD MMM')} – ${dayjs(reportFilters.dateRange[1]).format('DD MMM')}` });
  if (reportFilters.scoreRules.length) appliedFilterChips.push({ key: 'scoreRules', label: `${reportFilters.scoreRules.length} score condition${reportFilters.scoreRules.length === 1 ? '' : 's'}` });
  if (!summary && loading) return <div className="tl-reports-page"><div className="page-heading tl-page-heading"><div><Title level={2}>QA reports</Title><Paragraph>Review your team’s completed evaluations.</Paragraph></div></div><ContentLoader label="Loading reports" minHeight={480} /></div>;
  return <div className="tl-reports-page">
    <div className="page-heading tl-page-heading"><div><Title level={2}>QA reports</Title><Paragraph>Review your team’s completed evaluations.</Paragraph></div></div>
    {error && <Alert type="error" showIcon closable={{ onClose: () => setError('') }} title="Reports could not be loaded" description={error} />}
    <Card className="tl-inbox-card">
      <div className="tl-inbox-head"><Segmented<ReportSegment> className="tl-report-segments" value={segment} onChange={(value) => { setSegment(value); setPage(1); }} options={[{ label: `All ${summary?.total ?? 0}`, value: 'all' }, { label: `Needs review ${summary?.pending ?? 0}`, value: 'attention' }, { label: `Critical ${summary?.critical_open ?? 0}`, value: 'critical' }, { label: `Coaching ${summary?.coaching_open ?? 0}`, value: 'coaching' }, { label: `Closed ${summary?.closed ?? 0}`, value: 'closed' }]} /><Text type="secondary">{total} matching reports</Text></div>
      <div className="tl-filter-toolbar">
        <Search prefix={<SearchOutlined />} allowClear enterButton="Search" placeholder="Agent, phone, team, or QA" value={searchInput} onChange={(event) => { const value = event.target.value; setSearchInput(value); if (!value) { setSearch(''); setPage(1); } }} onSearch={(value) => { setSearch(value.trim()); setPage(1); }} className="tl-filter-search" />
        <div className="tl-filter-toolbar__actions">
          <Select aria-label="Sort reports" value={ordering} onChange={(value) => { setOrdering(value); setPage(1); }} options={[{ value: '-completed_at', label: 'Newest first' }, { value: 'completed_at', label: 'Oldest first' }, { value: 'score', label: 'Lowest score' }, { value: '-score', label: 'Highest score' }, { value: 'coaching_due_at', label: 'Coaching due' }]} />
          <Badge count={advancedFilterCount} size="small" offset={[-4, 4]}><Button type={filtersOpen ? 'primary' : 'default'} icon={<FilterOutlined />} onClick={() => setFiltersOpen(true)}>Filters</Button></Badge>
        </div>
      </div>
      {appliedFilterChips.length > 0 && <div className="tl-filter-status"><div>{appliedFilterChips.map((chip) => <Tag key={chip.key} closable onClose={(event) => { event.preventDefault(); clearFilterGroup(chip.key); }}>{chip.label}</Tag>)}</div><Button type="link" size="small" onClick={clearAllReportFilters}>Clear all</Button></div>}
      <Table<QAReport> rowKey="id" columns={columns} dataSource={reports} loading={{ spinning: loading, delay: 180, description: 'Updating reports' }} rowClassName={(row) => `tl-report-row${row.critical_errors.length ? ' is-critical' : ''}${row.leader_status === 'pending' ? ' is-pending' : ''}`} onRow={(row) => ({ onClick: () => void openReport(row) })} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No reports match this view" /> }} scroll={{ x: 1120 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `${count} reports` }} onChange={(pagination) => { setLoading(true); setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20); }} />
    </Card>
    <TeamLeaderReportFilters open={filtersOpen} value={reportFilters} options={summary?.filters} onClose={() => setFiltersOpen(false)} onApply={(next) => { setReportFilters(next); setPage(1); setFiltersOpen(false); }} />
    <ReportManagementDrawer report={selected} loading={detailLoading} actionStatus={actionStatus} actionNote={actionNote} coachingDue={coachingDue} saving={savingAction} rangeRequest={rangeRequest} onClose={() => { setSelected(null); setRangeRequest(null); }} onStatusChange={setActionStatus} onNoteChange={setActionNote} onDueChange={setCoachingDue} onSubmit={() => void submitAction()} onPlayPatch={(startSeconds, endSeconds) => setRangeRequest({ startSeconds, endSeconds, requestId: Date.now() })} />
  </div>;
}

interface ReportManagementDrawerProps {
  report: QAReportDetail | null;
  loading: boolean;
  actionStatus?: TeamLeaderReportStatus;
  actionNote: string;
  coachingDue: Dayjs | null;
  saving: boolean;
  rangeRequest: AudioRangeRequest | null;
  onClose: () => void;
  onStatusChange: (value: TeamLeaderReportStatus | undefined) => void;
  onNoteChange: (value: string) => void;
  onDueChange: (value: Dayjs | null) => void;
  onSubmit: () => void;
  onPlayPatch: (startSeconds: number, endSeconds: number) => void;
}

function EvidencePatches({ patches, onPlay }: { patches: QAEvidencePatch[]; onPlay: (startSeconds: number, endSeconds: number) => void }) {
  if (!patches.length) return null;
  return <div className="tl-patch-list">{patches.map((patch, index) => <Button type="text" className="tl-patch" key={patch.id} onClick={() => onPlay(patch.start_ms / 1000, patch.end_ms / 1000)}>
    <span className="tl-patch__play"><PlayCircleOutlined /></span>
    <span className="tl-patch__body"><strong>Evidence {index + 1}</strong><small>{patch.comment || 'Play the referenced recording segment'}</small></span>
    <span className="tl-patch__time"><strong>{formatEvidenceTime(patch.start_ms)} – {formatEvidenceTime(patch.end_ms)}</strong><small>{Math.max(1, Math.round((patch.end_ms - patch.start_ms) / 1000))} sec</small></span>
  </Button>)}</div>;
}

function criterionScoreColor(percent: number) {
  if (percent >= 100) return '#20b486';
  if (percent >= 75) return '#3b82f6';
  if (percent >= 50) return '#f5a524';
  return '#e05260';
}

function EvaluationEntry({ label, score, maximum, evidence, critical = false, onPlay }: { label: string; score?: number; maximum?: number; evidence?: QACriterionEvidence; critical?: boolean; onPlay: (startSeconds: number, endSeconds: number) => void }) {
  const hasScore = score !== undefined && maximum !== undefined;
  const scorePercent = hasScore && maximum > 0 ? Math.max(0, Math.min(100, (score / maximum) * 100)) : 0;
  const evidenceSummary = evidence?.patches.length
    ? `${evidence.patches.length} linked recording segment${evidence.patches.length === 1 ? '' : 's'}`
    : critical || (hasScore && score < maximum)
      ? 'No timestamp evidence attached'
      : null;
  return <article className={`tl-evaluation-entry${critical ? ' is-critical' : ''}`}>
    <div className="tl-evaluation-entry__head"><span><strong>{label}</strong>{evidenceSummary && <small>{evidenceSummary}</small>}</span>{critical ? <Tag color="error" variant="filled">Critical violation</Tag> : hasScore && <div className="tl-criterion-score"><strong>{score}/{maximum}</strong><Progress percent={scorePercent} showInfo={false} size="small" strokeColor={criterionScoreColor(scorePercent)} /></div>}</div>
    {evidence?.comment && <p className="tl-evaluation-entry__comment">{evidence.comment}</p>}
    <EvidencePatches patches={evidence?.patches ?? []} onPlay={onPlay} />
  </article>;
}

function ReportManagementDrawer({ report, loading, actionStatus, actionNote, coachingDue, saving, rangeRequest, onClose, onStatusChange, onNoteChange, onDueChange, onSubmit, onPlayPatch }: ReportManagementDrawerProps) {
  const snapshot = report?.scorecard_snapshot as QAScorecard | undefined;
  const hasScores = Boolean(report && Object.keys(report.scores).length);
  const actionNeedsNote = actionStatus && ['coaching_planned', 'coaching_completed', 'escalated', 'returned_to_qa'].includes(actionStatus);
  const scorecardItems = report && snapshot ? snapshot.categories.map((category) => {
    const entries = category.criteria.filter((criterion) => Object.hasOwn(report.scores, criterion.key) || Boolean(report.criterion_evidence?.[criterion.key]));
    if (!entries.length) return null;
    const subtotal = category.criteria.reduce((sum, criterion) => sum + Number(report.scores[criterion.key] ?? 0), 0);
    const patchCount = entries.reduce((sum, criterion) => sum + (report.criterion_evidence?.[criterion.key]?.patches.length ?? 0), 0);
    return {
      key: category.key,
      label: <div className="tl-category-label"><span><strong>{category.label}</strong>{patchCount > 0 && <small>{patchCount} evidence patch{patchCount === 1 ? '' : 'es'}</small>}</span><Tag>{hasScores ? `${subtotal}/${category.max_score}` : 'Not scored'}</Tag></div>,
      children: <div className="tl-evaluation-entries">{entries.map((criterion) => <EvaluationEntry key={criterion.key} label={criterion.label} score={Object.hasOwn(report.scores, criterion.key) ? Number(report.scores[criterion.key]) : undefined} maximum={criterion.max_score} evidence={report.criterion_evidence?.[criterion.key]} onPlay={onPlayPatch} />)}</div>,
    };
  }).filter((item): item is NonNullable<typeof item> => Boolean(item)) : [];
  const criticalLabels = new Map(snapshot?.critical_errors.map((item) => [item.value, item.label]) ?? []);
  const evaluation = report ? <div className="tl-report-evaluation">
    {report.critical_errors.length > 0 && <Alert type="error" showIcon icon={<WarningFilled />} title="Automatic fail · immediate escalation" description={`${report.critical_errors.length} critical violation${report.critical_errors.length === 1 ? '' : 's'} recorded by QA. Open a timestamp below to play the exact supporting segment.`} />}
    {report.critical_errors.length > 0 && <section className="tl-critical-evidence"><div className="tl-section-heading"><span><strong>Critical violations</strong><small>QA explanation and recording evidence</small></span><Tag color="error">{report.critical_errors.length}</Tag></div><div className="tl-evaluation-entries">{report.critical_errors.map((criticalKey) => <EvaluationEntry key={criticalKey} label={criticalLabels.get(criticalKey) ?? criticalKey} evidence={report.critical_error_evidence?.[criticalKey]} critical onPlay={onPlayPatch} />)}</div></section>}
    {report.critical_errors.length > 0 && !hasScores && <Alert type="info" showIcon title="Scorecard waived for escalation" description="A critical error determines this outcome, so numeric criterion scores were not required." />}
    {scorecardItems.length > 0 && <section className="tl-scorecard-review"><div className="tl-section-heading"><span><strong>Scorecard breakdown</strong><small>Subheading scores, QA comments, and timestamp evidence</small></span></div><Collapse items={scorecardItems} defaultActiveKey={scorecardItems.filter((item) => report && snapshot?.categories.find((category) => category.key === item.key)?.criteria.some((criterion) => Boolean(report.criterion_evidence?.[criterion.key]))).map((item) => item.key)} expandIconPlacement="end" /></section>}
    <div className="tl-narrative-grid"><ReportText label="What happened and why it matters" value={report.feedback_summary} /><ReportText label="Strengths observed" value={report.strengths} /><ReportText label="Expected behavior" value={report.expected_behavior} /><ReportText label="Recommended coaching / follow-up" value={report.coaching_plan} /></div>
  </div> : null;
  const activity = report ? <div className="tl-activity"><div className="tl-call-facts"><div><small>Phone</small><strong>{report.phone_number || 'Not available'}</strong></div><div><small>Call date</small><strong>{report.call_date ? dayjs(report.call_date).format('DD MMM YYYY, h:mm A') : 'Not available'}</strong></div><div><small>Disposition</small><strong>{report.call.disposition || 'Not available'}</strong></div><div><small>Talk time</small><strong>{Math.floor(report.call.talk_time / 60)}m {report.call.talk_time % 60}s</strong></div><div><small>Direction</small><strong>{report.call.call_direction}</strong></div><div><small>QA analyst</small><strong>{report.reviewer_name}</strong></div></div><Timeline items={[...report.workflow_events.map((event) => ({ color: event.to_status === 'escalated' ? 'red' : event.to_status === 'returned_to_qa' ? 'orange' : event.to_status === 'closed' ? 'green' : 'blue', children: <div className="tl-timeline-entry"><strong>{event.event_type === 'note_added' ? 'Management note added' : `${event.from_status_label} → ${event.to_status_label}`}</strong><span>{event.note || 'No additional note'}</span>{event.coaching_due_at && <small>Coaching due {dayjs(event.coaching_due_at).format('DD MMM YYYY, h:mm A')}</small>}<small>{event.actor_name} · {dayjs(event.created_at).format('DD MMM YYYY, h:mm A')}</small></div> })), { color: 'gray', children: <div className="tl-timeline-entry"><strong>QA report submitted</strong><span>{report.rating_label} · {report.critical_errors.length ? 'Scorecard waived' : `${report.score}%`}</span><small>{report.reviewer_name} · {report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Date unavailable'}</small></div> }]} /></div> : null;
  return <Drawer open={Boolean(report) || loading} onClose={onClose} size="min(900px, calc(100vw - 24px))" destroyOnHidden classNames={{ body: 'tl-report-drawer__body' }} title={report ? <div className="tl-drawer-title"><Avatar size={38}>{initials(report.agent_name || report.agent_user)}</Avatar><span><strong>{report.agent_name || report.agent_user}</strong><small>{report.team_name} · {report.project_name || 'Unmapped project'}</small></span></div> : 'QA report'} extra={report && <Tag color={WORKFLOW_COLORS[report.leader_status]}>{report.leader_status_label}</Tag>}>
    {loading ? <ContentLoader label="Opening QA report" minHeight={480} /> : report && <div className="tl-report-detail data-reveal">
      <div className={`tl-report-hero${report.critical_errors.length ? ' is-critical' : ''}`}><Progress type="circle" percent={Number(report.score ?? 0)} size={94} status={report.critical_errors.length ? 'exception' : Number(report.score ?? 0) >= 85 ? 'success' : 'normal'} format={() => report.critical_errors.length ? 'FAIL' : `${report.score}%`} /><div><Tag color={outcomeColor(report)} variant="filled">{report.rating_label}</Tag><Title level={4}>{report.outcome_label}</Title><Text type="secondary">Submitted by {report.reviewer_name} · {report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Date unavailable'}</Text></div></div>
      {report.call.recording_available && <Card size="small" className="tl-recording-card" title="Call recording"><AudioPlayer call={report.call} rangeRequest={rangeRequest} /></Card>}
      <Tabs items={[{ key: 'evaluation', label: 'Evaluation', children: evaluation }, { key: 'activity', label: `Activity (${report.workflow_events.length})`, children: activity }]} />
      <Card size="small" className="tl-action-card" title={<span><strong>Management decision</strong><small>Review the report above before recording the next action</small></span>}>
        <Form layout="vertical">
          <div className="tl-action-grid"><Form.Item label="Next action"><Select allowClear placeholder="Add note only" value={actionStatus} onChange={onStatusChange} options={NEXT_ACTIONS[report.leader_status].map((value) => ({ value, label: WORKFLOW_LABELS[value] }))} /></Form.Item>{actionStatus === 'coaching_planned' && <Form.Item label="Coaching deadline" required><DatePicker showTime value={coachingDue} minDate={dayjs()} onChange={onDueChange} className="tl-action-date" /></Form.Item>}</div>
          {actionStatus === 'returned_to_qa' && <Alert className="tl-return-alert" type="warning" showIcon title="Return this report for reassessment" description={`The report will leave your active queue. ${report.reviewer_name} will regain editing access and receive an in-app notification; email delivery activates when production mail is enabled.`} />}
          <Form.Item label={actionStatus === 'returned_to_qa' ? 'Reason for reassessment' : actionNeedsNote ? 'Action note' : 'Management note'} required={Boolean(actionNeedsNote)}><TextArea rows={3} maxLength={4000} showCount value={actionNote} onChange={(event) => onNoteChange(event.target.value)} placeholder={actionStatus === 'returned_to_qa' ? 'Identify the inaccurate, incomplete, or unsupported part of the report and what must be reassessed…' : actionStatus === 'coaching_planned' ? 'Document the coaching focus and expected outcome…' : actionStatus === 'escalated' ? 'Explain the risk and who should follow up…' : 'Add context for the next person reviewing this report…'} /></Form.Item>
          <div className="tl-action-card__footer"><Text type="secondary">Current state: {report.leader_status_label}</Text><Button type="primary" danger={actionStatus === 'returned_to_qa'} icon={<SendOutlined />} loading={saving} onClick={onSubmit}>{actionStatus === 'returned_to_qa' ? 'Return to QA' : 'Record decision'}</Button></div>
        </Form>
      </Card>
    </div>}
  </Drawer>;
}

function BasicReports() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isQa = user?.role === 'qa' && !user.is_superuser;
  const [reports, setReports] = useState<QAReport[]>([]);
  const [selected, setSelected] = useState<QAReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  useEffect(() => { let active = true; api<PaginatedResponse<QAReport>>(`/api/v1/calls/reports/?page=${page}&page_size=${pageSize}`).then((data) => { if (active) { setReports(data.results); setTotal(data.count); setError(''); } }).catch((requestError: unknown) => { if (active) setError(requestError instanceof ApiError ? requestError.message : 'QA reports could not be loaded.'); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [page, pageSize]);
  const sharedColumns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <span className="report-agent"><strong>{row.agent_name || row.agent_user}</strong><small>{row.team_name || 'Unassigned team'}</small></span> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => value || 'Unmapped' },
  ];
  const columns: TableProps<QAReport>['columns'] = isQa ? [
    ...sharedColumns,
    { title: 'Status', key: 'status', width: 150, render: (_, row) => row.status === 'revision_required' ? <Tag color="warning">Needs revision</Tag> : ['completed', 'disputed'].includes(row.status) ? <Tag color="success">Submitted</Tag> : <Tag color="processing">In progress</Tag> },
    { title: 'Result', key: 'result', width: 170, render: (_, row) => ['completed', 'disputed'].includes(row.status) ? row.critical_errors.length ? <Tag color="error" icon={<WarningFilled />}>Critical fail</Tag> : <span className="qa-report-result"><strong>{row.score}%</strong><small>{row.rating_label}</small></span> : <Text type="secondary">—</Text> },
    { title: 'Updated', key: 'completed', width: 170, render: (_, row) => <span className={row.status === 'revision_required' ? 'qa-returned-date' : 'qa-report-date'}>{row.status === 'revision_required' && <strong>Returned</strong>}<small>{dayjs(row.revision_requested_at || row.completed_at || row.assigned_at).format('DD MMM YYYY, h:mm A')}</small></span> },
    { title: '', key: 'actions', width: 156, align: 'right', render: (_, row) => ['assigned', 'in_progress', 'revision_required'].includes(row.status) ? <Button type="link" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={() => navigate(`/calls?analysis=${encodeURIComponent(row.call_id)}`)}>{row.status === 'revision_required' ? 'Reassess' : 'Continue'}</Button> : <Button type="text" shape="circle" icon={<EyeOutlined />} aria-label="View report" onClick={() => setSelected(row)} /> },
  ] : [
    ...sharedColumns,
    { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer' },
    { title: 'Score', key: 'score', width: 120, align: 'center', render: (_, row) => row.status === 'completed' ? <strong>{row.critical_errors.length ? 'FAIL' : `${row.score}%`}</strong> : row.status === 'revision_required' ? <Tag color="orange">Revision</Tag> : <Tag>Draft</Tag> },
    { title: 'Result', key: 'result', width: 200, render: (_, row) => row.status === 'completed' ? <Tag color={outcomeColor(row)} icon={row.critical_errors.length ? <WarningFilled /> : undefined}>{row.rating_label}</Tag> : row.status === 'revision_required' ? <Tag color="warning">Returned by Team Leader</Tag> : <Text type="secondary">In progress</Text> },
    { title: 'Updated', key: 'completed', width: 170, render: (_, row) => row.status === 'revision_required' && row.revision_requested_at ? <span className="qa-returned-date"><strong>Returned</strong><small>{dayjs(row.revision_requested_at).format('DD MMM YYYY, h:mm A')}</small></span> : row.completed_at ? dayjs(row.completed_at).format('DD MMM YYYY, h:mm A') : '—' },
    { title: '', key: 'actions', width: 56, align: 'center', render: (_, row) => <Button type="text" shape="circle" icon={<EyeOutlined />} aria-label="View report" onClick={() => setSelected(row)} /> },
  ];
  const snapshot = selected?.scorecard_snapshot as QAScorecard | undefined;
  return <div className="reports-page"><div className="page-heading"><div><Text className="page-kicker">QA WORKFLOW</Text><Title level={2}>{isQa ? 'My QA reports' : 'Team reports'}</Title><Paragraph>{isQa ? 'Continue active evaluations, address returned work, and review submitted reports.' : 'Completed evaluations delivered by QA analysts.'}</Paragraph></div>{isQa && <Button type="primary" className="page-heading__action" icon={<SearchOutlined />} onClick={() => navigate('/calls')}>Find a call</Button>}</div><Card className="reports-card">{error && <Alert type="error" showIcon title="Unable to load reports" description={error} />}<Table<QAReport> rowKey="id" columns={columns} dataSource={reports} loading={{ spinning: loading, delay: 180, description: 'Updating reports' }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No QA reports yet" /> }} scroll={{ x: isQa ? 820 : 980 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `${count} reports` }} onChange={(pagination) => { setLoading(true); setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20); }} /></Card><Drawer open={Boolean(selected)} onClose={() => setSelected(null)} size="large" destroyOnHidden title={<Space><FileDoneOutlined /><span>QA report</span></Space>}>{selected && <ReportContents report={selected} snapshot={snapshot} />}</Drawer></div>;
}

function ReportContents({ report, snapshot }: { report: QAReport; snapshot?: QAScorecard }) {
  const hasScores = Object.keys(report.scores).length > 0;
  return <div className="report-detail"><div className={`report-detail__score${report.critical_errors.length ? ' is-critical' : ''}`}><Progress type="dashboard" percent={Number(report.score ?? 0)} status={report.critical_errors.length ? 'exception' : Number(report.score ?? 0) >= 85 ? 'success' : 'normal'} format={() => report.critical_errors.length ? 'FAIL' : `${report.score}%`} /><span><Tag color={outcomeColor(report)}>{report.rating_label || report.status_label}</Tag><strong>{report.outcome_label}</strong><small>{report.agent_name} · {report.team_name}</small></span></div>{report.critical_errors.length > 0 && !hasScores && <Alert type="info" showIcon title="Scorecard waived for escalation" description="Numeric scores were not required because a critical error determined the outcome." />}{hasScores && snapshot?.categories?.map((category) => { const subtotal = category.criteria.reduce((sum, criterion) => sum + Number(report.scores[criterion.key] ?? 0), 0); return <section className="report-category-block" key={category.key}><div className="report-category"><span><strong>{category.label}</strong><small>{subtotal}/{category.max_score}</small></span><Progress percent={(subtotal / category.max_score) * 100} showInfo={false} size="small" /></div></section>; })}{report.feedback_summary && <ReportText label="What happened and why it matters" value={report.feedback_summary} />}{report.strengths && <ReportText label="Strengths observed" value={report.strengths} />}{report.expected_behavior && <ReportText label="Expected behavior" value={report.expected_behavior} />}{report.coaching_plan && <ReportText label="Recommended coaching / follow-up" value={report.coaching_plan} />}<div className="report-detail__meta"><Text type="secondary">Reviewed by {report.reviewer_name}</Text><Text type="secondary">{report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Draft'}</Text></div></div>;
}

function ReportText({ label, value }: { label: string; value: string }) {
  return <section className="report-text"><strong>{label}</strong><Paragraph>{value || 'Not specified'}</Paragraph></section>;
}
