import {
  AlertOutlined,
  ArrowRightOutlined,
  AuditOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileDoneOutlined,
  InboxOutlined,
  RiseOutlined,
  ReloadOutlined,
  SearchOutlined,
  WarningFilled,
} from '@ant-design/icons';
import { Alert, Button, Card, Col, Progress, Row, Statistic, Table, Tag, Tooltip, Typography, type TableProps } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { ContentLoader } from '../components/LoadingStates';
import { api } from '../lib/api';
import { appDate } from '../lib/datetime';
import type { CallEvent, DashboardSummary, PaginatedResponse, QAReport, QAReportSummary } from '../types';
import { ProjectPerformancePage } from './ProjectPerformancePage';

const { Title, Text } = Typography;

function greeting() {
  return appDate().hour() < 12 ? 'morning' : appDate().hour() < 18 ? 'afternoon' : 'evening';
}

function formatDuration(seconds: number | null) {
  if (!seconds) return '0:00';
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
}

const statusColor: Record<string, string> = { downloaded: 'success', downloading: 'processing', retrying: 'warning', failed: 'error', skipped: 'default', pending: 'default' };

export function DashboardPage() {
  const { user } = useAuth();
  if (user?.role === 'qa' && !user.is_superuser) return <QAAnalystCommandCenter />;
  if (user?.role === 'team_leader' && !user.is_superuser) return <TeamLeaderCommandCenter />;
  if (user?.role === 'project_manager' && !user.is_superuser) return <ProjectPerformancePage overview />;
  return <OperationsDashboard />;
}

function QAAnalystCommandCenter() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [calls, setCalls] = useState<DashboardSummary | null>(null);
  const [summary, setSummary] = useState<QAReportSummary | null>(null);
  const [reports, setReports] = useState<QAReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<DashboardSummary>('/api/v1/dashboard/summary/'),
      api<QAReportSummary>('/api/v1/calls/reports/summary/'),
      api<PaginatedResponse<QAReport>>('/api/v1/calls/reports/?page=1&page_size=6&ordering=-completed_at'),
    ])
      .then(([callData, reportSummary, reportPage]) => {
        if (!active) return;
        setCalls(callData);
        setSummary(reportSummary);
        setReports(reportPage.results);
        setError('');
      })
      .catch(() => { if (active) setError('Your QA workspace could not be loaded. Check the connection and try again.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reloadKey]);

  const readyCalls = (calls?.recent_calls ?? []).filter((call) => call.recording_available && (!call.reservation || call.reservation.is_mine));
  const retry = () => { setLoading(true); setError(''); setReloadKey((value) => value + 1); };
  const reportColumns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="table-primary"><strong>{row.agent_name || row.agent_user || 'Unassigned'}</strong><small>{row.project_name || 'Unmapped project'}</small></div> },
    { title: 'Status', key: 'status', width: 142, render: (_, row) => row.status === 'revision_required' ? <Tag color="warning">Needs revision</Tag> : ['completed', 'disputed'].includes(row.status) ? <Tag color="success">Submitted</Tag> : <Tag color="processing">In progress</Tag> },
    { title: 'Result', key: 'result', width: 125, render: (_, row) => ['completed', 'disputed'].includes(row.status) ? row.critical_errors.length ? <Tag color="error">Critical fail</Tag> : <strong>{row.score}%</strong> : <Text type="secondary">—</Text> },
    { title: 'Updated', key: 'updated', width: 140, render: (_, row) => <div className="leader-date"><strong>{appDate(row.revision_requested_at || row.completed_at || row.assigned_at).format('DD MMM')}</strong><small>{appDate(row.revision_requested_at || row.completed_at || row.assigned_at).format('h:mm A')} ET</small></div> },
    { title: '', key: 'action', width: 128, align: 'right', render: (_, row) => ['assigned', 'in_progress', 'revision_required'].includes(row.status) ? <Button type="link" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={() => navigate(`/calls?analysis=${encodeURIComponent(row.call_id)}`)}>{row.status === 'revision_required' ? 'Reassess' : 'Continue'}</Button> : <Button type="link" icon={<EyeOutlined />} onClick={() => navigate('/queue')}>View report</Button> },
  ];
  const callColumns: TableProps<CallEvent>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="table-primary"><strong>{row.agent_name || row.agent_user || 'Unassigned'}</strong><small>{row.project_name || 'Unmapped project'}</small></div> },
    { title: 'Phone', dataIndex: 'phone_number', key: 'phone', width: 150, render: (value) => <strong>{value || '—'}</strong> },
    { title: 'Talk time', dataIndex: 'talk_time', key: 'duration', width: 100, render: formatDuration },
    { title: 'Received', dataIndex: 'received_at', key: 'received', width: 125, render: (value) => `${appDate(value).format('h:mm A')} ET` },
    { title: '', key: 'action', width: 112, align: 'right', render: (_, row) => <Button type="link" icon={<SearchOutlined />} onClick={() => navigate(`/calls?analysis=${encodeURIComponent(row.id)}`)}>{row.reservation?.is_mine ? 'Continue' : 'Analyze'}</Button> },
  ];

  return <div className="page-stack qa-command">
    <div className="page-heading">
      <Title level={2} className="page-title">Good {greeting()}, {user?.first_name}.</Title>
      <Button type="primary" className="page-heading__action" icon={<SearchOutlined />} onClick={() => navigate('/calls')}>Find a call</Button>
    </div>
    {error && <Alert type="error" showIcon title="Unable to load QA workspace" description={error} action={<Button icon={<ReloadOutlined />} onClick={retry}>Try again</Button>} />}
    {loading ? <ContentLoader label="Loading QA workspace" minHeight={460} /> : !error && <div className="qa-command__content data-reveal">
      <section className="qa-priority-grid" aria-label="QA workload summary">
        <QAPriorityCard title="Ready now" value={calls?.metrics.recordings_ready ?? 0} detail="Recordings received in the last 24 hours" icon={<DownloadOutlined />} tone="primary" onClick={() => navigate('/calls')} />
        <QAPriorityCard title="Awaiting audio" value={calls?.metrics.recordings_pending ?? 0} detail="Recordings still being retrieved" icon={<ClockCircleOutlined />} tone="warning" onClick={() => navigate('/calls')} />
        <QAPriorityCard title="Reports submitted" value={summary?.total ?? 0} detail="Your completed QA evaluations" icon={<FileDoneOutlined />} tone="success" onClick={() => navigate('/queue')} />
      </section>

      <Card className="content-card qa-work-card" title="My recent work" extra={<Link to="/queue">View all <ArrowRightOutlined /></Link>}>
        <Table<QAReport> rowKey="id" size="small" columns={reportColumns} dataSource={reports} pagination={false} scroll={{ x: 720 }} locale={{ emptyText: <div className="leader-empty"><FileDoneOutlined /><strong>No QA reports yet</strong></div> }} />
      </Card>

      <Card className="content-card qa-ready-card" title="Ready to analyze" extra={<Link to="/calls">Open library <ArrowRightOutlined /></Link>}>
        <Table<CallEvent> rowKey="id" size="small" columns={callColumns} dataSource={readyCalls} pagination={false} scroll={{ x: 620 }} locale={{ emptyText: <div className="leader-empty"><CheckCircleFilled /><strong>No ready calls in recent activity</strong></div> }} />
      </Card>
    </div>}
  </div>;
}

function QAPriorityCard({ title, value, detail, icon, tone, onClick }: { title: string; value: number; detail: string; icon: ReactNode; tone: 'primary' | 'warning' | 'success'; onClick: () => void }) {
  return <Card hoverable role="button" tabIndex={0} className={`qa-priority qa-priority--${tone}`} classNames={{ body: 'qa-priority__body' }} onClick={onClick} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick(); } }}><div className="qa-priority__head"><span>{icon}</span><ArrowRightOutlined /></div><Statistic className="qa-priority__stat" classNames={{ title: 'qa-priority__title', content: 'qa-priority__value' }} title={title} value={value} /><Text type="secondary">{detail}</Text></Card>;
}

function TeamLeaderCommandCenter() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [calls, setCalls] = useState<DashboardSummary | null>(null);
  const [summary, setSummary] = useState<QAReportSummary | null>(null);
  const [pendingReports, setPendingReports] = useState<QAReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([
      api<DashboardSummary>('/api/v1/dashboard/summary/'),
      api<QAReportSummary>('/api/v1/calls/reports/summary/'),
      api<PaginatedResponse<QAReport>>('/api/v1/calls/reports/?segment=attention&ordering=-completed_at&page=1&page_size=6'),
    ])
      .then(([callData, reportSummary, reportPage]) => {
        if (!active) return;
        setCalls(callData);
        setSummary(reportSummary);
        setPendingReports(reportPage.results);
        setError('');
      })
      .catch(() => { if (active) setError('Your team command center could not be loaded. Check the connection and try again.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reloadKey]);

  const retry = () => { setLoading(true); setError(''); setReloadKey((value) => value + 1); };
  const reportColumns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="table-primary"><strong>{row.agent_name || row.agent_user || 'Unassigned'}</strong><small>{row.team_name || 'Unassigned team'}</small></div> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => value || 'Unmapped' },
    { title: 'Result', key: 'result', width: 140, render: (_, row) => row.critical_errors.length ? <Tag color="error" icon={<WarningFilled />}>Critical fail</Tag> : <div className="leader-score"><strong>{row.score ?? 0}%</strong><small>{row.rating_label}</small></div> },
    { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer', width: 150 },
    { title: 'Submitted', key: 'submitted', width: 142, render: (_, row) => row.completed_at ? <div className="leader-date"><strong>{appDate(row.completed_at).format('DD MMM')}</strong><small>{appDate(row.completed_at).format('h:mm A')} ET</small></div> : '—' },
    { title: '', key: 'action', width: 48, align: 'center', render: () => <ArrowRightOutlined className="leader-row-arrow" /> },
  ];
  const callColumns: TableProps<CallEvent>['columns'] = [
    { title: 'Phone', dataIndex: 'phone_number', key: 'phone', render: (value) => <strong>{value || '—'}</strong> },
    { title: 'Agent', key: 'agent', render: (_, row) => <div className="table-primary"><strong>{row.agent_name || row.agent_user || 'Unassigned'}</strong><small>{row.team_name || 'Unassigned team'}</small></div> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => value || 'Unmapped' },
    { title: 'Talk time', dataIndex: 'talk_time', key: 'duration', width: 100, render: formatDuration },
    { title: 'Received', dataIndex: 'received_at', key: 'received', width: 120, render: (value) => <Tooltip title={`${appDate(value).format('DD MMM YYYY, h:mm A')} ET`}>{appDate(value).format('h:mm A')} ET</Tooltip> },
  ];

  return <div className="page-stack leader-command">
    <div className="page-heading leader-command__heading">
      <Title level={2} className="page-title">Good {greeting()}, {user?.first_name}.</Title>
      <Button type="primary" className="page-heading__action" icon={<InboxOutlined />} onClick={() => navigate('/queue')}>Open QA inbox</Button>
    </div>
    {error && <Alert type="error" showIcon title="Unable to load command center" description={error} action={<Button icon={<ReloadOutlined />} onClick={retry}>Try again</Button>} />}
    {loading ? <ContentLoader label="Loading team command center" minHeight={480} /> : !error && <div className="leader-command__content data-reveal">
      <section className="leader-metric-grid" aria-label="Team priorities">
        <LeaderMetric title="Needs review" value={summary?.pending ?? 0} detail="New QA reports awaiting your decision" icon={<InboxOutlined />} tone="primary" onClick={() => navigate('/queue')} />
        <LeaderMetric title="Critical open" value={summary?.critical_open ?? 0} detail="Reports requiring immediate attention" icon={<AlertOutlined />} tone="danger" onClick={() => navigate('/queue')} />
        <LeaderMetric title="Coaching overdue" value={summary?.overdue ?? 0} detail={`${summary?.coaching_open ?? 0} coaching plan${summary?.coaching_open === 1 ? '' : 's'} in progress`} icon={<ClockCircleOutlined />} tone="warning" onClick={() => navigate('/queue')} />
        <LeaderMetric title="Team quality" value={summary?.average_score ?? 0} precision={1} suffix="%" detail={`Across ${summary?.total ?? 0} submitted reports`} icon={<RiseOutlined />} tone={!summary?.total ? 'primary' : (summary.average_score ?? 0) >= 85 ? 'success' : (summary.average_score ?? 0) >= 75 ? 'warning' : 'danger'} onClick={() => navigate('/queue')} />
      </section>

      <Card className="content-card leader-attention-card" title="Reports awaiting decision" extra={<Link to="/queue">View all <ArrowRightOutlined /></Link>}>
        <Table<QAReport> rowKey="id" size="small" columns={reportColumns} dataSource={pendingReports} pagination={false} scroll={{ x: 760 }} rowClassName={() => 'leader-report-row'} onRow={() => ({ onClick: () => navigate('/queue') })} locale={{ emptyText: <div className="leader-empty"><CheckCircleFilled /><strong>No reports awaiting decision</strong></div> }} />
      </Card>

      <Card className="content-card leader-calls-card" title="Recent team calls" extra={<Link to="/calls">Open call library <ArrowRightOutlined /></Link>}>
        <Table<CallEvent> rowKey="id" size="small" columns={callColumns} dataSource={calls?.recent_calls ?? []} pagination={false} scroll={{ x: 680 }} locale={{ emptyText: <div className="leader-empty"><CustomerServiceOutlined /><strong>No recent calls</strong></div> }} />
      </Card>
    </div>}
  </div>;
}

function LeaderMetric({ title, value, detail, icon, tone, onClick, precision, suffix }: { title: string; value: number; detail: string; icon: ReactNode; tone: 'primary' | 'danger' | 'warning' | 'success'; onClick: () => void; precision?: number; suffix?: ReactNode }) {
  return <Card hoverable role="button" tabIndex={0} className={`leader-metric leader-metric--${tone}`} classNames={{ body: 'leader-metric__body' }} onClick={onClick} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick(); } }}><div className="leader-metric__head"><span>{icon}</span><ArrowRightOutlined /></div><Statistic className="leader-metric__stat" classNames={{ title: 'leader-metric__title', content: 'leader-metric__value' }} title={title} value={value} precision={precision} suffix={suffix} /><Text type="secondary">{detail}</Text></Card>;
}

function OperationsDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    api<DashboardSummary>('/api/v1/dashboard/summary/')
      .then((result) => { if (active) setData(result); })
      .catch(() => { if (active) setError('Dashboard data could not be loaded. Check your connection and try again.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const retry = () => {
    setLoading(true);
    setError('');
    api<DashboardSummary>('/api/v1/dashboard/summary/').then(setData).catch(() => setError('Dashboard data could not be loaded. Check your connection and try again.')).finally(() => setLoading(false));
  };
  const columns: TableProps<CallEvent>['columns'] = [
    { title: 'Call', key: 'call', render: (_, call) => <div className="table-primary"><strong>{call.call_id || `Lead ${call.lead_id}`}</strong><small>{call.phone_number}</small></div> },
    { title: 'Agent', key: 'agent', render: (_, row) => <Tooltip title={row.agent_user ? `Agent ID: ${row.agent_user}` : 'Agent ID unavailable'}>{row.agent_name || row.agent_user || 'Unassigned'}</Tooltip> },
    { title: 'Campaign', dataIndex: 'campaign', key: 'campaign', render: (value) => <Tag>{value || '—'}</Tag> },
    { title: 'Duration', dataIndex: 'talk_time', key: 'talk_time', render: formatDuration },
    { title: 'Recording', dataIndex: 'recording_download_status', key: 'recording', render: (value) => <Tag color={statusColor[value]}>{value.replace('_', ' ')}</Tag> },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', render: (value) => `${appDate(value).format('h:mm A')} ET` },
  ];

  return <div className="page-stack"><div className="page-heading"><Title level={2} className="page-title">Good {greeting()}, {user?.first_name}.</Title><Button type="primary" className="page-heading__action" icon={<AuditOutlined />} onClick={() => navigate('/queue')}>Start reviewing</Button></div>
    {error && <Alert type="error" showIcon title="Unable to load dashboard" description={error} action={<Button icon={<ReloadOutlined />} onClick={retry}>Try again</Button>} />}
    {loading ? <ContentLoader label="Loading dashboard" minHeight={420} /> : !error && <div className="data-reveal"><Row gutter={[16, 16]}><Col xs={24} sm={12} xl={6}><MetricCard order={0} title="Calls received" value={data?.metrics.total_calls ?? 0} icon={<CustomerServiceOutlined />} footer={<><span className="positive"><RiseOutlined /> Live intake</span><Text type="secondary">24 hours</Text></>} /></Col><Col xs={24} sm={12} xl={6}><MetricCard order={1} title="Recordings ready" value={data?.metrics.recordings_ready ?? 0} icon={<DownloadOutlined />} footer={<><span className="positive"><CheckCircleFilled /> Available</span><Text type="secondary">for review</Text></>} /></Col><Col xs={24} sm={12} xl={6}><MetricCard order={2} title="Awaiting recording" value={data?.metrics.recordings_pending ?? 0} icon={<ClockCircleOutlined />} footer={<span>Automatic retries active</span>} /></Col><Col xs={24} sm={12} xl={6}><MetricCard order={3} title="Average talk time" value={formatDuration(data?.metrics.avg_talk_time ?? 0)} icon={<BarChartVisual />} footer={<span>Across received calls</span>} /></Col></Row>
      <Row gutter={[16, 16]}><Col xs={24} xl={16}><Card className="content-card" title="Recent call activity" extra={<Link to="/calls">View library <ArrowRightOutlined /></Link>}><Table<CallEvent> className="content-table" rowKey="id" columns={columns} dataSource={data?.recent_calls ?? []} pagination={false} scroll={{ x: 760 }} /></Card></Col><Col xs={24} xl={8}><Card className="content-card quality-card" title="Review completion"><div className="quality-progress"><Progress type="circle" percent={data?.metrics.review_completion ?? 0} strokeColor="var(--qa-primary)" size={154} /><div><Text type="secondary">Reviews completed</Text><Title level={3} className="quality-total">{data?.metrics.reviewed ?? 0}</Title></div></div><div className="queue-breakdown"><div><span className="queue-dot queue-dot--purple" /><span><strong>Ready for review</strong><small>Recordings processed</small></span><b>{data?.metrics.recordings_ready ?? 0}</b></div><div><span className="queue-dot queue-dot--amber" /><span><strong>Processing</strong><small>Recording retrieval</small></span><b>{data?.metrics.recordings_pending ?? 0}</b></div></div><Link className="card-action" to="/queue">Open review queue <ArrowRightOutlined /></Link></Card></Col></Row></div>}
  </div>;
}

function MetricCard({ order, title, value, icon, footer }: { order: number; title: string; value: number | string; icon: ReactNode; footer: ReactNode }) {
  return <Card hoverable className={`metric-card metric-card--${order}`} classNames={{ body: 'metric-card__body' }}><Statistic classNames={{ title: 'metric-title', content: 'metric-value', prefix: 'metric-icon' }} title={title} value={value} prefix={icon} /><div className="metric-foot">{footer}</div></Card>;
}

function BarChartVisual() {
  return <span className="bars-icon" aria-hidden="true"><i /><i /><i /></span>;
}
