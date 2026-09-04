import { ArrowRightOutlined, AuditOutlined, CheckCircleFilled, ClockCircleOutlined, CustomerServiceOutlined, DownloadOutlined, MoreOutlined, RiseOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Col, Progress, Row, Skeleton, Statistic, Table, Tag, Tooltip, Typography, type TableProps } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { api } from '../lib/api';
import type { CallEvent, DashboardSummary } from '../types';

const { Title, Paragraph, Text } = Typography;

function formatDuration(seconds: number | null) {
  if (!seconds) return '0:00';
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
}

const statusColor: Record<string, string> = { downloaded: 'success', downloading: 'processing', retrying: 'warning', failed: 'error', skipped: 'default', pending: 'default' };

export function DashboardPage() {
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
    api<DashboardSummary>('/api/v1/dashboard/summary/')
      .then(setData)
      .catch(() => setError('Dashboard data could not be loaded. Check your connection and try again.'))
      .finally(() => setLoading(false));
  };

  const columns: TableProps<CallEvent>['columns'] = [
    { title: 'Call', key: 'call', render: (_, call) => <div className="table-primary"><strong>{call.call_id || `Lead ${call.lead_id}`}</strong><small>{call.phone_number}</small></div> },
    { title: 'Agent', key: 'agent', render: (_, row) => <Tooltip title={row.agent_user ? `Agent ID: ${row.agent_user}` : 'Agent ID unavailable'}>{row.agent_name || row.agent_user || 'Unassigned'}</Tooltip> },
    { title: 'Campaign', dataIndex: 'campaign', key: 'campaign', render: (value) => <Tag>{value || '—'}</Tag> },
    { title: 'Duration', dataIndex: 'talk_time', key: 'talk_time', render: formatDuration },
    { title: 'Recording', dataIndex: 'recording_download_status', key: 'recording', render: (value) => <Tag color={statusColor[value]}>{value.replace('_', ' ')}</Tag> },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', render: (value) => dayjs(value).format('h:mm A') },
    { title: '', key: 'actions', width: 48, render: () => <Button type="text" icon={<MoreOutlined />} aria-label="Call actions" /> },
  ];

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><Text className="eyebrow">OPERATIONS OVERVIEW</Text><Title level={2} className="page-title">Good {dayjs().hour() < 12 ? 'morning' : dayjs().hour() < 18 ? 'afternoon' : 'evening'}, {user?.first_name}.</Title><Paragraph className="page-subtitle">Here’s the quality pulse for your branch over the last 24 hours.</Paragraph></div>
        <Button type="primary" className="page-heading__action" icon={<AuditOutlined />} onClick={() => navigate('/queue')}>Start reviewing</Button>
      </div>

      {error && <Alert type="error" showIcon title="Unable to load dashboard" description={error} action={<Button onClick={retry}>Try again</Button>} />}
      {loading ? <Skeleton active paragraph={{ rows: 8 }} /> : !error && <>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} xl={6}><MetricCard order={0} title="Calls received" value={data?.metrics.total_calls ?? 0} icon={<CustomerServiceOutlined />} footer={<><span className="positive"><RiseOutlined /> Live intake</span><Text type="secondary">24 hours</Text></>} /></Col>
          <Col xs={24} sm={12} xl={6}><MetricCard order={1} title="Recordings ready" value={data?.metrics.recordings_ready ?? 0} icon={<DownloadOutlined />} footer={<><span className="positive"><CheckCircleFilled /> Available</span><Text type="secondary">for review</Text></>} /></Col>
          <Col xs={24} sm={12} xl={6}><MetricCard order={2} title="Awaiting recording" value={data?.metrics.recordings_pending ?? 0} icon={<ClockCircleOutlined />} footer={<span>Automatic retries active</span>} /></Col>
          <Col xs={24} sm={12} xl={6}><MetricCard order={3} title="Average talk time" value={formatDuration(data?.metrics.avg_talk_time ?? 0)} icon={<BarChartVisual />} footer={<span>Across received calls</span>} /></Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={16}>
            <Card className="content-card" classNames={{ header: 'content-card__header', title: 'content-card__title', extra: 'content-card__extra', body: 'content-card__body' }} title={<div><strong>Recent call activity</strong><small>Newest dialer events in your branch</small></div>} extra={<Link to="/calls">View library <ArrowRightOutlined /></Link>}>
              <Table<CallEvent> className="content-table" rowKey="id" columns={columns} dataSource={data?.recent_calls ?? []} pagination={false} scroll={{ x: 760 }} locale={{ emptyText: <div className="empty-table"><CustomerServiceOutlined className="empty-table__icon" /><strong>No calls have arrived yet</strong><span>Your connected dialer activity will appear here.</span></div> }} />
            </Card>
          </Col>
          <Col xs={24} xl={8}>
            <Card className="content-card quality-card" classNames={{ header: 'content-card__header', title: 'content-card__title', body: 'quality-card__body' }} title={<div><strong>Review completion</strong><small>Current assigned workload</small></div>}>
              <div className="quality-progress"><Progress type="circle" percent={data?.metrics.review_completion ?? 0} strokeColor="var(--qa-primary)" size={154} /><div><Text type="secondary">Reviews completed</Text><Title level={3} className="quality-total">{data?.metrics.reviewed ?? 0}</Title></div></div>
              <div className="queue-breakdown"><div><span className="queue-dot queue-dot--purple" /><span><strong>Ready for review</strong><small>Recordings processed</small></span><b>{data?.metrics.recordings_ready ?? 0}</b></div><div><span className="queue-dot queue-dot--amber" /><span><strong>Processing</strong><small>Recording retrieval</small></span><b>{data?.metrics.recordings_pending ?? 0}</b></div></div>
              <Link className="card-action" to="/queue">Open review queue <ArrowRightOutlined /></Link>
            </Card>
          </Col>
        </Row>
      </>}
    </div>
  );
}

function MetricCard({ order, title, value, icon, footer }: { order: number; title: string; value: number | string; icon: ReactNode; footer: ReactNode }) {
  return <Card hoverable className={`metric-card metric-card--${order}`} classNames={{ body: 'metric-card__body' }}><Statistic classNames={{ title: 'metric-title', content: 'metric-value', prefix: 'metric-icon' }} title={title} value={value} prefix={icon} /><div className="metric-foot">{footer}</div></Card>;
}

function BarChartVisual() {
  return <span className="bars-icon" aria-hidden="true"><i /><i /><i /></span>;
}
