import {
  AlertOutlined,
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  FileDoneOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SearchOutlined,
  SendOutlined,
  TeamOutlined,
  WarningFilled,
} from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Avatar,
  Badge,
  Button,
  Card,
  DatePicker,
  Drawer,
  Empty,
  Form,
  Input,
  Progress,
  Segmented,
  Select,
  Space,
  Statistic,
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
import { PortalLoader } from '../components/PortalLoader';
import { api, ApiError } from '../lib/api';
import type {
  PaginatedResponse,
  QAReport,
  QAReportDetail,
  QAReportSummary,
  QAScorecard,
  TeamLeaderReportStatus,
} from '../types';

const { Paragraph, Text, Title } = Typography;
const { RangePicker } = DatePicker;
const { TextArea, Search } = Input;

type ReportSegment = 'all' | 'attention' | 'critical' | 'coaching' | 'closed';

const WORKFLOW_COLORS: Record<TeamLeaderReportStatus, string> = {
  pending: 'warning',
  acknowledged: 'processing',
  coaching_planned: 'purple',
  coaching_completed: 'cyan',
  escalated: 'error',
  closed: 'success',
};

const NEXT_ACTIONS: Record<TeamLeaderReportStatus, TeamLeaderReportStatus[]> = {
  pending: ['acknowledged', 'coaching_planned', 'escalated'],
  acknowledged: ['coaching_planned', 'escalated', 'closed'],
  coaching_planned: ['coaching_completed', 'escalated'],
  coaching_completed: ['coaching_planned', 'closed'],
  escalated: ['coaching_planned', 'closed'],
  closed: ['acknowledged'],
};

const WORKFLOW_LABELS: Record<TeamLeaderReportStatus, string> = {
  pending: 'Needs review',
  acknowledged: 'Reviewed',
  coaching_planned: 'Plan coaching',
  coaching_completed: 'Coaching completed',
  escalated: 'Escalate',
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

function reportPriority(report: QAReport) {
  if (report.critical_errors.length) return { label: 'Critical', color: 'error' };
  if (Number(report.score ?? 0) < 80) return { label: 'High', color: 'warning' };
  if (Number(report.score ?? 0) < 85) return { label: 'Coaching', color: 'purple' };
  return { label: 'Routine', color: 'default' };
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
  const [project, setProject] = useState<string>();
  const [reviewer, setReviewer] = useState<string>();
  const [rating, setRating] = useState<string>();
  const [dateRange, setDateRange] = useState<[string, string] | null>(null);
  const [ordering, setOrdering] = useState('-completed_at');
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
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), segment, ordering });
    if (search) params.set('search', search);
    if (project) params.set('project', project);
    if (reviewer) params.set('reviewer', reviewer);
    if (rating) params.set('rating', rating);
    if (dateRange) { params.set('date_from', dateRange[0]); params.set('date_to', dateRange[1]); }
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
  }, [dateRange, ordering, page, pageSize, project, rating, reviewer, search, segment]);

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
    setSavingAction(true);
    try {
      const updated = await api<QAReportDetail>(`/api/v1/calls/reports/${selected.id}/actions/`, {
        method: 'POST',
        body: JSON.stringify({ leader_status: actionStatus, note: actionNote, coaching_due_at: coachingDue?.toISOString() }),
      });
      setSelected(updated);
      setReports((current) => current.map((report) => report.id === updated.id ? updated : report));
      setActionStatus(undefined);
      setActionNote('');
      setCoachingDue(null);
      void loadSummary();
      void message.success('Report workflow updated.');
    } catch (requestError) {
      void message.error(requestError instanceof Error ? requestError.message : 'The report could not be updated.');
    } finally {
      setSavingAction(false);
    }
  };

  const resetFilters = () => {
    setSearchInput(''); setSearch(''); setProject(undefined); setReviewer(undefined); setRating(undefined); setDateRange(null); setOrdering('-completed_at'); setPage(1);
  };

  const columns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="tl-agent"><Avatar size={34}>{initials(row.agent_name || row.agent_user)}</Avatar><span><strong>{row.agent_name || row.agent_user}</strong><small>{row.team_name || 'Unassigned team'}</small></span></div> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => <Text>{value || 'Unmapped'}</Text> },
    { title: 'Score', key: 'score', width: 138, align: 'center', render: (_, row) => <div className="tl-score-cell"><strong>{row.critical_errors.length ? 'FAIL' : `${row.score}%`}</strong><small>{row.critical_errors.length ? 'Critical error' : row.rating_label}</small></div> },
    { title: 'Priority', key: 'priority', width: 116, align: 'center', render: (_, row) => { const priority = reportPriority(row); return <Tag color={priority.color} variant="filled">{priority.label}</Tag>; } },
    { title: 'Workflow', key: 'workflow', width: 190, render: (_, row) => <div className="tl-workflow-cell"><Tag color={WORKFLOW_COLORS[row.leader_status]} variant="filled">{row.leader_status_label}</Tag>{isOverdue(row) && <small className="is-overdue"><ClockCircleOutlined /> Overdue</small>}{row.coaching_due_at && !isOverdue(row) && row.leader_status === 'coaching_planned' && <small>Due {dayjs(row.coaching_due_at).format('DD MMM')}</small>}</div> },
    { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer', width: 160 },
    { title: 'Submitted', key: 'completed', width: 150, render: (_, row) => row.completed_at ? <span className="tl-date"><strong>{dayjs(row.completed_at).format('DD MMM YYYY')}</strong><small>{dayjs(row.completed_at).format('h:mm A')}</small></span> : '—' },
    { title: '', key: 'action', width: 58, align: 'center', render: (_, row) => <Button type="text" shape="circle" icon={<ArrowRightOutlined />} aria-label={`Review ${row.agent_name}`} onClick={(event) => { event.stopPropagation(); void openReport(row); }} /> },
  ];

  const maxTrendCount = Math.max(1, ...(summary?.trend.map((point) => point.count) ?? [1]));
  const activeFilters = [project, reviewer, rating, dateRange].filter(Boolean).length;
  return <div className="tl-reports-page">
    <div className="page-heading tl-page-heading"><div><Text className="page-kicker">TEAM QUALITY OPERATIONS</Text><Title level={2}>QA report inbox</Title><Paragraph>Review evaluations, resolve risks, and keep coaching follow-up moving.</Paragraph></div><div className="tl-freshness"><Badge status="success" text="Live workflow" /><Text type="secondary">Updated {summary ? dayjs(summary.generated_at).format('h:mm A') : '—'}</Text></div></div>
    {error && <Alert type="error" showIcon closable={{ onClose: () => setError('') }} title="Unable to load the complete report workspace" description={error} />}
    <section className="tl-metric-grid" aria-label="Team report overview">
      <Card className="tl-metric tl-metric--attention" hoverable onClick={() => { setSegment('attention'); setPage(1); }}><Statistic title="Needs your review" value={summary?.pending ?? 0} prefix={<ClockCircleOutlined />} /><Text type="secondary">New QA submissions</Text></Card>
      <Card className="tl-metric tl-metric--critical" hoverable onClick={() => { setSegment('critical'); setPage(1); }}><Statistic title="Critical open" value={summary?.critical_open ?? 0} prefix={<AlertOutlined />} /><Text type="secondary">Immediate investigation</Text></Card>
      <Card className="tl-metric tl-metric--coaching" hoverable onClick={() => { setSegment('coaching'); setPage(1); }}><Statistic title="Coaching in flight" value={summary?.coaching_open ?? 0} prefix={<TeamOutlined />} /><Text type={summary?.overdue ? 'danger' : 'secondary'}>{summary?.overdue ?? 0} overdue</Text></Card>
      <Card className="tl-metric"><Statistic title="Average QA score" value={summary?.average_score ?? 0} precision={1} suffix="%" prefix={<CheckCircleOutlined />} /><Text type="secondary">Across {summary?.total ?? 0} reports</Text></Card>
      <Card className="tl-metric" hoverable onClick={() => { setSegment('all'); setPage(1); }}><Statistic title="Open below benchmark" value={summary?.below_benchmark_open ?? 0} prefix={<WarningFilled />} /><Text type="secondary">Below 85% and unresolved</Text></Card>
    </section>
    <Card className="tl-pulse-card" title={<span><strong>14-day QA pulse</strong><small>Submitted volume and daily average</small></span>} extra={<Text type="secondary">Team average {summary?.average_score?.toFixed(1) ?? '—'}%</Text>}>
      <div className="tl-trend" aria-label="Fourteen day QA report trend">{summary?.trend.map((point) => <div className="tl-trend__day" key={point.date} title={`${dayjs(point.date).format('DD MMM')}: ${point.count} reports, ${point.average_score ?? 'no'} average score`}><span className="tl-trend__score">{point.average_score !== null ? Math.round(point.average_score) : ''}</span><i style={{ height: `${Math.max(point.count ? 14 : 3, (point.count / maxTrendCount) * 100)}%` }} /><small>{dayjs(point.date).format('D')}</small></div>)}</div>
    </Card>
    <Card className="tl-inbox-card">
      <div className="tl-inbox-head"><Segmented<ReportSegment> value={segment} onChange={(value) => { setSegment(value); setPage(1); }} options={[{ label: `All ${summary?.total ?? 0}`, value: 'all' }, { label: `Needs review ${summary?.pending ?? 0}`, value: 'attention' }, { label: `Critical ${summary?.critical_open ?? 0}`, value: 'critical' }, { label: `Coaching ${summary?.coaching_open ?? 0}`, value: 'coaching' }, { label: `Closed ${summary?.closed ?? 0}`, value: 'closed' }]} /><Text type="secondary">{total} matching reports</Text></div>
      <div className="tl-filter-bar">
        <Search prefix={<SearchOutlined />} allowClear enterButton="Search" placeholder="Search agent, phone, team, or QA" value={searchInput} onChange={(event) => { const value = event.target.value; setSearchInput(value); if (!value) { setSearch(''); setPage(1); } }} onSearch={(value) => { setSearch(value.trim()); setPage(1); }} className="tl-filter-search" />
        <Select allowClear showSearch={{ optionFilterProp: 'label' }} placeholder="Project" value={project} onChange={(value) => { setProject(value); setPage(1); }} options={summary?.filters.projects.map((value) => ({ value, label: value }))} />
        <Select allowClear showSearch={{ optionFilterProp: 'label' }} placeholder="QA analyst" value={reviewer} onChange={(value) => { setReviewer(value); setPage(1); }} options={summary?.filters.reviewers.map((item) => ({ value: item.reviewer_id, label: `${item.reviewer__first_name} ${item.reviewer__last_name}`.trim() }))} />
        <Select allowClear placeholder="Rating" value={rating} onChange={(value) => { setRating(value); setPage(1); }} options={[{ value: 'excellent', label: 'Excellent' }, { value: 'very_good', label: 'Very Good' }, { value: 'good', label: 'Good' }, { value: 'needs_improvement', label: 'Needs Improvement' }, { value: 'unsatisfactory', label: 'Unsatisfactory' }, { value: 'automatic_fail', label: 'Automatic Fail' }]} />
        <RangePicker value={dateRange ? [dayjs(dateRange[0]), dayjs(dateRange[1])] : null} onChange={(dates) => { setDateRange(dates ? [dates[0]!.format('YYYY-MM-DD'), dates[1]!.format('YYYY-MM-DD')] : null); setPage(1); }} />
        <Select value={ordering} onChange={(value) => { setOrdering(value); setPage(1); }} options={[{ value: '-completed_at', label: 'Newest first' }, { value: 'completed_at', label: 'Oldest first' }, { value: 'score', label: 'Lowest score' }, { value: '-score', label: 'Highest score' }, { value: 'coaching_due_at', label: 'Coaching due' }]} />
        <Button icon={<ReloadOutlined />} disabled={!activeFilters && !search && ordering === '-completed_at'} onClick={resetFilters}>Reset</Button>
      </div>
      <Table<QAReport> rowKey="id" columns={columns} dataSource={reports} loading={loading} rowClassName={(row) => `tl-report-row${row.critical_errors.length ? ' is-critical' : ''}${row.leader_status === 'pending' ? ' is-pending' : ''}`} onRow={(row) => ({ onClick: () => void openReport(row) })} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No reports match this view" /> }} scroll={{ x: 1120 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `${count} reports` }} onChange={(pagination) => { setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20); }} />
    </Card>
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

function ReportManagementDrawer({ report, loading, actionStatus, actionNote, coachingDue, saving, rangeRequest, onClose, onStatusChange, onNoteChange, onDueChange, onSubmit, onPlayPatch }: ReportManagementDrawerProps) {
  const snapshot = report?.scorecard_snapshot as QAScorecard | undefined;
  const hasScores = Boolean(report && Object.keys(report.scores).length);
  const actionNeedsNote = actionStatus && ['coaching_planned', 'coaching_completed', 'escalated'].includes(actionStatus);
  const evaluation = report ? <div className="tl-report-evaluation">
    {report.critical_errors.length > 0 && <Alert type="error" showIcon icon={<WarningFilled />} title="Automatic fail · immediate escalation" description={`${report.critical_errors.length} critical error${report.critical_errors.length === 1 ? '' : 's'} recorded by QA.`} />}
    {report.critical_errors.length > 0 && !hasScores && <Alert type="info" showIcon title="Scorecard waived for escalation" description="A critical error determines this outcome, so numeric criterion scores were not required." />}
    {hasScores && snapshot?.categories?.map((category) => {
      const subtotal = category.criteria.reduce((sum, criterion) => sum + Number(report.scores[criterion.key] ?? 0), 0);
      const annotated = category.criteria.filter((criterion) => { const evidence = report.criterion_evidence?.[criterion.key]; return Boolean(evidence?.comment || evidence?.patches?.length); });
      return <section className="tl-score-category" key={category.key}><div className="tl-score-category__head"><span><strong>{category.label}</strong><small>{subtotal} of {category.max_score} points</small></span><Progress percent={(subtotal / category.max_score) * 100} showInfo={false} size="small" /></div>{annotated.length > 0 && <div className="tl-evidence-list">{annotated.map((criterion) => { const evidence = report.criterion_evidence[criterion.key]; return <div className="tl-evidence" key={criterion.key}><strong>{criterion.label}</strong>{evidence.comment && <p>{evidence.comment}</p>}{evidence.patches.length > 0 && <div>{evidence.patches.map((patch) => <Button size="small" icon={<PlayCircleOutlined />} key={patch.id} onClick={() => onPlayPatch(patch.start_ms / 1000, patch.end_ms / 1000)}>{formatEvidenceTime(patch.start_ms)}–{formatEvidenceTime(patch.end_ms)}{patch.comment ? ` · ${patch.comment}` : ''}</Button>)}</div>}</div>; })}</div>}</section>;
    })}
    <div className="tl-narrative-grid"><ReportText label="What happened and why it matters" value={report.feedback_summary} /><ReportText label="Strengths observed" value={report.strengths} /><ReportText label="Expected behavior" value={report.expected_behavior} /><ReportText label="Recommended coaching / follow-up" value={report.coaching_plan} /></div>
  </div> : null;
  const activity = report ? <div className="tl-activity"><div className="tl-call-facts"><div><small>Phone</small><strong>{report.phone_number || 'Not available'}</strong></div><div><small>Call date</small><strong>{report.call_date ? dayjs(report.call_date).format('DD MMM YYYY, h:mm A') : 'Not available'}</strong></div><div><small>Disposition</small><strong>{report.call.disposition || 'Not available'}</strong></div><div><small>Talk time</small><strong>{Math.floor(report.call.talk_time / 60)}m {report.call.talk_time % 60}s</strong></div><div><small>Direction</small><strong>{report.call.call_direction}</strong></div><div><small>QA analyst</small><strong>{report.reviewer_name}</strong></div></div><Timeline items={[...report.workflow_events.map((event) => ({ color: event.to_status === 'escalated' ? 'red' : event.to_status === 'closed' ? 'green' : 'blue', children: <div className="tl-timeline-entry"><strong>{event.event_type === 'note_added' ? 'Management note added' : `${event.from_status_label} → ${event.to_status_label}`}</strong><span>{event.note || 'No additional note'}</span>{event.coaching_due_at && <small>Coaching due {dayjs(event.coaching_due_at).format('DD MMM YYYY, h:mm A')}</small>}<small>{event.actor_name} · {dayjs(event.created_at).format('DD MMM YYYY, h:mm A')}</small></div> })), { color: 'gray', children: <div className="tl-timeline-entry"><strong>QA report submitted</strong><span>{report.rating_label} · {report.critical_errors.length ? 'Scorecard waived' : `${report.score}%`}</span><small>{report.reviewer_name} · {report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Date unavailable'}</small></div> }]} /></div> : null;
  return <Drawer open={Boolean(report) || loading} onClose={onClose} size="min(900px, calc(100vw - 24px))" destroyOnHidden classNames={{ body: 'tl-report-drawer__body' }} title={report ? <div className="tl-drawer-title"><Avatar size={38}>{initials(report.agent_name || report.agent_user)}</Avatar><span><strong>{report.agent_name || report.agent_user}</strong><small>{report.team_name} · {report.project_name || 'Unmapped project'}</small></span></div> : 'QA report'} extra={report && <Tag color={WORKFLOW_COLORS[report.leader_status]}>{report.leader_status_label}</Tag>}>
    {loading ? <div className="tl-detail-loader"><PortalLoader label="Opening QA report…" /></div> : report && <div className="tl-report-detail">
      <div className={`tl-report-hero${report.critical_errors.length ? ' is-critical' : ''}`}><Progress type="circle" percent={Number(report.score ?? 0)} size={94} status={report.critical_errors.length ? 'exception' : Number(report.score ?? 0) >= 85 ? 'success' : 'normal'} format={() => report.critical_errors.length ? 'FAIL' : `${report.score}%`} /><div><Tag color={outcomeColor(report)} variant="filled">{report.rating_label}</Tag><Title level={4}>{report.outcome_label}</Title><Text type="secondary">Submitted by {report.reviewer_name} · {report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Date unavailable'}</Text></div></div>
      {report.call.recording_available && <Card size="small" className="tl-recording-card" title="Call recording"><AudioPlayer call={report.call} rangeRequest={rangeRequest} /></Card>}
      <Card size="small" className="tl-action-card" title={<span><strong>Management action</strong><small>Every update is recorded in the report history</small></span>}><Form layout="vertical"><div className="tl-action-grid"><Form.Item label="Next action"><Select allowClear placeholder="Add note only" value={actionStatus} onChange={onStatusChange} options={NEXT_ACTIONS[report.leader_status].map((value) => ({ value, label: WORKFLOW_LABELS[value] }))} /></Form.Item>{actionStatus === 'coaching_planned' && <Form.Item label="Coaching deadline" required><DatePicker showTime value={coachingDue} minDate={dayjs()} onChange={onDueChange} className="tl-action-date" /></Form.Item>}</div><Form.Item label={actionNeedsNote ? 'Action note' : 'Management note'} required={Boolean(actionNeedsNote)}><TextArea rows={3} maxLength={4000} showCount value={actionNote} onChange={(event) => onNoteChange(event.target.value)} placeholder={actionStatus === 'coaching_planned' ? 'Document the coaching focus and expected outcome…' : actionStatus === 'escalated' ? 'Explain the risk and who should follow up…' : 'Add context for the next person reviewing this report…'} /></Form.Item><div className="tl-action-card__footer"><Text type="secondary">Current state: {report.leader_status_label}</Text><Button type="primary" icon={<SendOutlined />} loading={saving} onClick={onSubmit}>Record action</Button></div></Form></Card>
      <Tabs items={[{ key: 'evaluation', label: 'Evaluation', children: evaluation }, { key: 'activity', label: `Activity (${report.workflow_events.length})`, children: activity }]} />
    </div>}
  </Drawer>;
}

function BasicReports() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [reports, setReports] = useState<QAReport[]>([]);
  const [selected, setSelected] = useState<QAReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  useEffect(() => { let active = true; api<PaginatedResponse<QAReport>>(`/api/v1/calls/reports/?page=${page}&page_size=${pageSize}`).then((data) => { if (active) { setReports(data.results); setTotal(data.count); setError(''); } }).catch((requestError: unknown) => { if (active) setError(requestError instanceof ApiError ? requestError.message : 'QA reports could not be loaded.'); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [page, pageSize]);
  const columns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <span className="report-agent"><strong>{row.agent_name || row.agent_user}</strong><small>{row.team_name || 'Unassigned team'}</small></span> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => value || 'Unmapped' }, { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer' },
    { title: 'Score', key: 'score', width: 120, align: 'center', render: (_, row) => row.status === 'completed' ? <strong>{row.critical_errors.length ? 'FAIL' : `${row.score}%`}</strong> : <Tag>Draft</Tag> },
    { title: 'Result', key: 'result', width: 200, render: (_, row) => row.status === 'completed' ? <Tag color={outcomeColor(row)} icon={row.critical_errors.length ? <WarningFilled /> : undefined}>{row.rating_label}</Tag> : <Text type="secondary">In progress</Text> },
    { title: 'Submitted', key: 'completed', width: 170, render: (_, row) => row.completed_at ? dayjs(row.completed_at).format('DD MMM YYYY, h:mm A') : '—' },
    { title: '', key: 'actions', width: user?.role === 'qa' ? 170 : 56, align: 'center', render: (_, row) => user?.role === 'qa' && row.status === 'in_progress' ? <Button type="link" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={() => navigate(`/calls?analysis=${encodeURIComponent(row.call_id)}`)}>Continue analysis</Button> : <Button type="text" shape="circle" icon={<EyeOutlined />} aria-label="View report" onClick={() => setSelected(row)} /> },
  ];
  const snapshot = selected?.scorecard_snapshot as QAScorecard | undefined;
  return <div className="reports-page"><div className="page-heading"><div><Text className="page-kicker">QA WORKFLOW</Text><Title level={2}>{user?.role === 'qa' ? 'My QA reports' : 'Team reports'}</Title><Paragraph>{user?.role === 'qa' ? 'Your drafts and submitted evaluations.' : 'Completed evaluations delivered by QA analysts.'}</Paragraph></div></div><Card className="reports-card">{error && <Alert type="error" showIcon title="Unable to load reports" description={error} />}<Table<QAReport> rowKey="id" columns={columns} dataSource={reports} loading={loading} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No QA reports yet" /> }} scroll={{ x: 980 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `${count} reports` }} onChange={(pagination) => { setLoading(true); setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20); }} /></Card><Drawer open={Boolean(selected)} onClose={() => setSelected(null)} size="large" destroyOnHidden title={<Space><FileDoneOutlined /><span>QA report</span></Space>}>{selected && <ReportContents report={selected} snapshot={snapshot} />}</Drawer></div>;
}

function ReportContents({ report, snapshot }: { report: QAReport; snapshot?: QAScorecard }) {
  const hasScores = Object.keys(report.scores).length > 0;
  return <div className="report-detail"><div className={`report-detail__score${report.critical_errors.length ? ' is-critical' : ''}`}><Progress type="dashboard" percent={Number(report.score ?? 0)} status={report.critical_errors.length ? 'exception' : Number(report.score ?? 0) >= 85 ? 'success' : 'normal'} format={() => report.critical_errors.length ? 'FAIL' : `${report.score}%`} /><span><Tag color={outcomeColor(report)}>{report.rating_label || report.status_label}</Tag><strong>{report.outcome_label}</strong><small>{report.agent_name} · {report.team_name}</small></span></div>{report.critical_errors.length > 0 && !hasScores && <Alert type="info" showIcon title="Scorecard waived for escalation" description="Numeric scores were not required because a critical error determined the outcome." />}{hasScores && snapshot?.categories?.map((category) => { const subtotal = category.criteria.reduce((sum, criterion) => sum + Number(report.scores[criterion.key] ?? 0), 0); return <section className="report-category-block" key={category.key}><div className="report-category"><span><strong>{category.label}</strong><small>{subtotal}/{category.max_score}</small></span><Progress percent={(subtotal / category.max_score) * 100} showInfo={false} size="small" /></div></section>; })}<ReportText label="What happened and why it matters" value={report.feedback_summary} /><ReportText label="Strengths observed" value={report.strengths} /><ReportText label="Expected behavior" value={report.expected_behavior} /><ReportText label="Recommended coaching / follow-up" value={report.coaching_plan} /><div className="report-detail__meta"><Text type="secondary">Reviewed by {report.reviewer_name}</Text><Text type="secondary">{report.completed_at ? dayjs(report.completed_at).format('DD MMM YYYY, h:mm A') : 'Draft'}</Text></div></div>;
}

function ReportText({ label, value }: { label: string; value: string }) {
  return <section className="report-text"><strong>{label}</strong><Paragraph>{value || 'Not specified'}</Paragraph></section>;
}
