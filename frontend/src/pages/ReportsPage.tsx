import { ArrowRightOutlined, EyeOutlined, FileDoneOutlined, WarningFilled } from '@ant-design/icons';
import { Alert, Button, Card, Drawer, Empty, Progress, Space, Table, Tag, Typography, type TableProps } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { formatEvidenceTime } from '../components/CriterionEvidenceEditor';
import { api, ApiError } from '../lib/api';
import type { PaginatedResponse, QAReport, QAScorecard } from '../types';

const { Paragraph, Text, Title } = Typography;

function outcomeColor(report: QAReport) {
  if (report.critical_errors.length) return 'error';
  const score = Number(report.score ?? 0);
  if (score >= 90) return 'success';
  if (score >= 85) return 'processing';
  return 'warning';
}

export function ReportsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [reports, setReports] = useState<QAReport[]>([]);
  const [selected, setSelected] = useState<QAReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let active = true;
    api<PaginatedResponse<QAReport>>(`/api/v1/calls/reports/?page=${page}&page_size=${pageSize}`)
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
  }, [page, pageSize]);

  const columns: TableProps<QAReport>['columns'] = [
    { title: 'Agent', key: 'agent', render: (_, row) => <span className="report-agent"><strong>{row.agent_name || row.agent_user}</strong><small>{row.team_name || 'Unassigned team'}</small></span> },
    { title: 'Project', dataIndex: 'project_name', key: 'project', render: (value) => value || 'Unmapped' },
    { title: 'QA analyst', dataIndex: 'reviewer_name', key: 'reviewer' },
    { title: 'Score', key: 'score', width: 120, align: 'center', render: (_, row) => row.status === 'completed' ? <strong>{row.score}%</strong> : <Tag>Draft</Tag> },
    { title: 'Result', key: 'result', width: 200, render: (_, row) => row.status === 'completed' ? <Tag color={outcomeColor(row)} icon={row.critical_errors.length ? <WarningFilled /> : undefined}>{row.rating_label}</Tag> : <Text type="secondary">In progress</Text> },
    { title: 'Submitted', key: 'completed', width: 170, render: (_, row) => row.completed_at ? dayjs(row.completed_at).format('DD MMM YYYY, h:mm A') : '—' },
    {
      title: '',
      key: 'actions',
      width: user?.role === 'qa' ? 170 : 56,
      align: 'center',
      render: (_, row) => user?.role === 'qa' && row.status === 'in_progress'
        ? <Button type="link" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={() => navigate(`/calls?analysis=${encodeURIComponent(row.call_id)}`)}>Continue analysis</Button>
        : <Button type="text" shape="circle" icon={<EyeOutlined />} aria-label="View report" onClick={() => setSelected(row)} />,
    },
  ];

  const snapshot = selected?.scorecard_snapshot as QAScorecard | undefined;
  return <div className="reports-page">
    <div className="page-heading"><div><Text className="page-kicker">QA WORKFLOW</Text><Title level={2}>{user?.role === 'qa' ? 'My QA reports' : 'Team reports'}</Title><Paragraph>{user?.role === 'qa' ? 'Your drafts and submitted evaluations.' : 'Completed evaluations delivered by QA analysts.'}</Paragraph></div></div>
    <Card className="reports-card">
      {error && <Alert type="error" showIcon title="Unable to load reports" description={error} />}
      <Table<QAReport> rowKey="id" columns={columns} dataSource={reports} loading={loading} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No QA reports yet" /> }} scroll={{ x: 980 }} pagination={{ current: page, pageSize, total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `${count} reports` }} onChange={(pagination) => { setLoading(true); setPage(pagination.current ?? 1); setPageSize(pagination.pageSize ?? 20); }} />
    </Card>
    <Drawer open={Boolean(selected)} onClose={() => setSelected(null)} size="large" destroyOnHidden title={<Space><FileDoneOutlined /><span>QA report</span></Space>}>
      {selected && <div className="report-detail">
        <div className={`report-detail__score${selected.critical_errors.length ? ' is-critical' : ''}`}><Progress type="dashboard" percent={Number(selected.score ?? 0)} status={selected.critical_errors.length ? 'exception' : Number(selected.score ?? 0) >= 85 ? 'success' : 'normal'} /><span><Tag color={outcomeColor(selected)}>{selected.rating_label || selected.status_label}</Tag><strong>{selected.outcome_label}</strong><small>{selected.agent_name} · {selected.team_name}</small></span></div>
        {selected.critical_errors.length > 0 && <div className="report-critical"><WarningFilled /><span><strong>Automatic fail · immediate escalation</strong><small>{selected.critical_errors.length} critical error{selected.critical_errors.length === 1 ? '' : 's'} recorded</small></span></div>}
        {snapshot?.categories?.map((category) => {
          const subtotal = category.criteria.reduce((sum, criterion) => sum + Number(selected.scores[criterion.key] ?? 0), 0);
          const annotated = category.criteria.filter((criterion) => {
            const evidence = selected.criterion_evidence?.[criterion.key];
            return Boolean(evidence?.comment || evidence?.patches?.length);
          });
          return <section className="report-category-block" key={category.key}>
            <div className="report-category"><span><strong>{category.label}</strong><small>{subtotal}/{category.max_score}</small></span><Progress percent={(subtotal / category.max_score) * 100} showInfo={false} size="small" /></div>
            {annotated.length > 0 && <div className="report-evidence-list">{annotated.map((criterion) => {
              const evidence = selected.criterion_evidence[criterion.key];
              return <div className="report-evidence" key={criterion.key}>
                <strong>{criterion.label}</strong>
                {evidence.comment && <p>{evidence.comment}</p>}
                {evidence.patches.length > 0 && <div>{evidence.patches.map((patch) => <Tag className="report-evidence__tag" key={patch.id}>{formatEvidenceTime(patch.start_ms)}–{formatEvidenceTime(patch.end_ms)}{patch.comment ? ` · ${patch.comment}` : ''}</Tag>)}</div>}
              </div>;
            })}</div>}
          </section>;
        })}
        <ReportText label="What happened and why it matters" value={selected.feedback_summary} />
        <ReportText label="Strengths observed" value={selected.strengths} />
        <ReportText label="Expected behavior" value={selected.expected_behavior} />
        <ReportText label="Recommended coaching / follow-up" value={selected.coaching_plan} />
        <div className="report-detail__meta"><Text type="secondary">Reviewed by {selected.reviewer_name}</Text><Text type="secondary">{selected.completed_at ? dayjs(selected.completed_at).format('DD MMM YYYY, h:mm A') : 'Draft'}</Text></div>
      </div>}
    </Drawer>
  </div>;
}

function ReportText({ label, value }: { label: string; value: string }) {
  return <section className="report-text"><strong>{label}</strong><Paragraph>{value || 'Not specified'}</Paragraph></section>;
}
