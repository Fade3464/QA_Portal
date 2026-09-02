import { ArrowRightOutlined, AuditOutlined, CheckCircleFilled, ClockCircleOutlined, CustomerServiceOutlined, DownloadOutlined, MoreOutlined, RiseOutlined } from '@ant-design/icons';
import { Button, Card, Col, Progress, Row, Skeleton, Statistic, Table, Tag, Typography, type TableProps } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
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
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<DashboardSummary>('/api/v1/dashboard/summary/').then(setData).finally(() => setLoading(false));
  }, []);

  const columns: TableProps<CallEvent>['columns'] = [
    { title: 'Call', key: 'call', render: (_, call) => <div className="table-primary"><strong>{call.call_id || `Lead ${call.lead_id}`}</strong><small>{call.phone_number}</small></div> },
    { title: 'Agent', dataIndex: 'agent_user', key: 'agent_user', render: (value) => value || 'Unassigned' },
    { title: 'Campaign', dataIndex: 'campaign', key: 'campaign', render: (value) => <Tag>{value || '—'}</Tag> },
    { title: 'Duration', dataIndex: 'talk_time', key: 'talk_time', render: formatDuration },
    { title: 'Recording', dataIndex: 'recording_download_status', key: 'recording', render: (value) => <Tag color={statusColor[value]}>{value.replace('_', ' ')}</Tag> },
    { title: 'Received', dataIndex: 'received_at', key: 'received_at', render: (value) => dayjs(value).format('h:mm A') },
    { title: '', key: 'actions', width: 48, render: () => <Button type="text" icon={<MoreOutlined />} aria-label="Call actions" /> },
  ];

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><Text className="eyebrow">OPERATIONS OVERVIEW</Text><Title level={2}>Good {dayjs().hour() < 12 ? 'morning' : dayjs().hour() < 18 ? 'afternoon' : 'evening'}, {user?.first_name}.</Title><Paragraph>Here’s the quality pulse for your branch over the last 24 hours.</Paragraph></div>
        <Button type="primary" icon={<AuditOutlined />}><Link to="/queue">Start reviewing</Link></Button>
      </div>

      {loading ? <Skeleton active paragraph={{ rows: 8 }} /> : <>
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} xl={6}><Card hoverable className="metric-card"><Statistic title="Calls received" value={data?.metrics.total_calls ?? 0} prefix={<CustomerServiceOutlined />} /><div className="metric-foot"><span className="positive"><RiseOutlined /> Live intake</span><Text type="secondary">24 hours</Text></div></Card></Col>
          <Col xs={24} sm={12} xl={6}><Card hoverable className="metric-card"><Statistic title="Recordings ready" value={data?.metrics.recordings_ready ?? 0} prefix={<DownloadOutlined />} /><div className="metric-foot"><span className="positive"><CheckCircleFilled /> Available</span><Text type="secondary">for review</Text></div></Card></Col>
          <Col xs={24} sm={12} xl={6}><Card hoverable className="metric-card"><Statistic title="Awaiting recording" value={data?.metrics.recordings_pending ?? 0} prefix={<ClockCircleOutlined />} /><div className="metric-foot"><span>Automatic retries active</span></div></Card></Col>
          <Col xs={24} sm={12} xl={6}><Card hoverable className="metric-card"><Statistic title="Average talk time" value={formatDuration(data?.metrics.avg_talk_time ?? 0)} prefix={<BarChartVisual />} /><div className="metric-foot"><span>Across received calls</span></div></Card></Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} xl={16}>
            <Card className="content-card" title={<div><strong>Recent call activity</strong><small>Newest dialer events in your branch</small></div>} extra={<Link to="/calls">View library <ArrowRightOutlined /></Link>}>
              <Table<CallEvent> rowKey="id" columns={columns} dataSource={data?.recent_calls ?? []} pagination={false} scroll={{ x: 760 }} locale={{ emptyText: <div className="empty-table"><CustomerServiceOutlined /><strong>No calls have arrived yet</strong><span>Your connected dialer activity will appear here.</span></div> }} />
            </Card>
          </Col>
          <Col xs={24} xl={8}>
            <Card className="content-card quality-card" title={<div><strong>Review completion</strong><small>Current assigned workload</small></div>}>
              <div className="quality-progress"><Progress type="circle" percent={data?.metrics.review_completion ?? 0} strokeColor="var(--qa-primary)" size={154} /><div><Text type="secondary">Reviews completed</Text><Title level={3}>{data?.metrics.reviewed ?? 0}</Title></div></div>
              <div className="queue-breakdown"><div><span className="queue-dot queue-dot--purple" /><span><strong>Ready for review</strong><small>Recordings processed</small></span><b>{data?.metrics.recordings_ready ?? 0}</b></div><div><span className="queue-dot queue-dot--amber" /><span><strong>Processing</strong><small>Recording retrieval</small></span><b>{data?.metrics.recordings_pending ?? 0}</b></div></div>
              <Link className="card-action" to="/queue">Open review queue <ArrowRightOutlined /></Link>
            </Card>
          </Col>
        </Row>
      </>}
    </div>
  );
}

function BarChartVisual() {
  return <span className="bars-icon" aria-hidden="true"><i /><i /><i /></span>;
}
