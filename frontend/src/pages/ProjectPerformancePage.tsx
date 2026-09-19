import {
  ArrowRightOutlined,
  AuditOutlined,
  CheckCircleOutlined,
  FileSearchOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { Alert, Button, Card, Empty, Progress, Segmented, Select, Statistic, Table, Typography, type TableProps } from 'antd';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ContentLoader } from '../components/LoadingStates';
import { MaterialSymbol } from '../components/MaterialSymbol';
import { api, ApiError } from '../lib/api';
import { appCalendarDate, appDate } from '../lib/datetime';
import type { ProjectPerformance } from '../types';

const { Paragraph, Text, Title } = Typography;
type WindowDays = 7 | 30 | 90;

function scoreTone(score: number | null) {
  if (score === null) return 'neutral';
  if (score >= 85) return 'success';
  if (score >= 75) return 'warning';
  return 'danger';
}

function scoreColor(score: number | null) {
  if (score === null) return '#94a3b8';
  if (score >= 85) return '#20b486';
  if (score >= 75) return '#f5a524';
  return '#e05260';
}

function PerformanceMetric({ title, value, suffix, detail, icon, tone }: { title: string; value: number; suffix?: string; detail: string; icon: ReactNode; tone: 'primary' | 'success' | 'warning' | 'danger' | 'neutral' }) {
  return <Card className={`pm-metric pm-metric--${tone}`} classNames={{ body: 'pm-metric__body' }}>
    <div className="pm-metric__icon">{icon}</div>
    <Statistic title={title} value={value} precision={suffix === '%' ? 1 : 0} suffix={suffix} />
    <Text type="secondary">{detail}</Text>
  </Card>;
}

function QualityTrend({ data }: { data: ProjectPerformance['trend'] }) {
  const scored = data.filter((point) => point.average_score !== null);
  if (!scored.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No scored evaluations in this period" />;
  const width = 1080;
  const height = 310;
  const left = 48;
  const right = 24;
  const top = 24;
  const bottom = 42;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const x = (index: number) => left + (index / Math.max(1, data.length - 1)) * chartWidth;
  const y = (score: number) => top + (1 - score / 100) * chartHeight;
  const points = data
    .map((point, index) => point.average_score === null ? null : `${x(index)},${y(point.average_score)}`)
    .filter(Boolean)
    .join(' ');
  const maxVolume = Math.max(1, ...data.map((point) => point.evaluated));
  const labelIndexes = new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]);
  return <div className="pm-trend" role="img" aria-label={`Daily average QA score over ${data.length} days`}>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0, 50, 85, 100].map((score) => <g key={score}>
        <line x1={left} x2={width - right} y1={y(score)} y2={y(score)} className={score === 85 ? 'pm-trend__benchmark' : 'pm-trend__grid'} />
        <text x={left - 9} y={y(score) + 4} textAnchor="end" className="pm-trend__axis">{score}</text>
      </g>)}
      {data.map((point, index) => <rect key={point.date} x={x(index) - 3} y={height - bottom - (point.evaluated / maxVolume) * 34} width="6" height={(point.evaluated / maxVolume) * 34} rx="3" className="pm-trend__volume"><title>{point.evaluated} evaluations · {appCalendarDate(point.date).format('DD MMM')}</title></rect>)}
      <polyline points={points} className="pm-trend__line" />
      {data.map((point, index) => point.average_score === null ? null : <circle key={point.date} cx={x(index)} cy={y(point.average_score)} r="4" className="pm-trend__point"><title>{appCalendarDate(point.date).format('DD MMM')}: {point.average_score}% across {point.evaluated} evaluations</title></circle>)}
      {data.map((point, index) => labelIndexes.has(index) ? <text key={point.date} x={x(index)} y={height - 8} textAnchor={index === 0 ? 'start' : index === data.length - 1 ? 'end' : 'middle'} className="pm-trend__axis">{appCalendarDate(point.date).format('DD MMM')}</text> : null)}
    </svg>
    <div className="pm-trend__legend"><span><i className="is-score" />Average QA score</span><span><i className="is-volume" />Evaluations</span><span><i className="is-benchmark" />85% benchmark</span></div>
  </div>;
}

export function ProjectPerformancePage({ overview = false }: { overview?: boolean }) {
  const navigate = useNavigate();
  const [data, setData] = useState<ProjectPerformance | null>(null);
  const [days, setDays] = useState<WindowDays>(30);
  const [project, setProject] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) setLoading(true); });
    const params = new URLSearchParams({ days: String(days) });
    if (project) params.set('project', project);
    api<ProjectPerformance>(`/api/v1/dashboard/project-performance/?${params}`)
      .then((result) => { if (active) { setData(result); setError(''); } })
      .catch((requestError: unknown) => { if (active) setError(requestError instanceof ApiError ? requestError.message : 'Project performance could not be loaded.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [days, project]);

  const projectOptions = useMemo(() => (data?.projects ?? []).map((value) => ({ value, label: value })), [data?.projects]);
  const columns: TableProps<ProjectPerformance['teams'][number]>['columns'] = [
    { title: 'Team', key: 'team', render: (_, row) => <div className="pm-team"><MaterialSymbol name={row.avatar} label="" /><span><strong>{row.name}</strong><small>{row.team_leader}</small></span></div> },
    { title: 'Evaluations', dataIndex: 'evaluated', key: 'evaluated', width: 120, align: 'center' },
    { title: 'Average score', key: 'score', width: 250, render: (_, row) => <div className="pm-team-score"><strong>{row.average_score === null ? 'N/A' : `${row.average_score}%`}</strong><Progress percent={row.average_score ?? 0} showInfo={false} size="small" strokeColor={scoreColor(row.average_score)} /></div> },
    { title: 'Critical', key: 'critical', width: 130, align: 'center', render: (_, row) => <span className={row.critical ? 'pm-risk-value' : ''}>{row.critical} <small>· {row.critical_rate}%</small></span> },
    { title: 'Below benchmark', dataIndex: 'below_benchmark', key: 'below', width: 150, align: 'center' },
  ];
  const metric = data?.metrics;
  return <div className={`page-stack pm-performance${overview ? ' pm-performance--overview' : ''}`}>
    <div className="page-heading pm-performance__heading">
      <div><Text className="eyebrow">PROJECT QUALITY</Text><Title level={2} className="page-title">{overview ? 'Project quality overview' : 'Team performance'}</Title><Paragraph className="page-subtitle">QA outcomes and team-level signals across the projects assigned to you.</Paragraph></div>
      <div className="pm-performance__actions"><Button icon={<FileSearchOutlined />} onClick={() => navigate('/calls')}>Call library</Button><Button type="primary" icon={<AuditOutlined />} onClick={() => navigate('/queue')}>QA reports</Button></div>
    </div>
    <div className="pm-performance__filters">
      <Select className="pm-project-select" allowClear showSearch={{ optionFilterProp: 'label' }} value={project || undefined} placeholder="All assigned projects" options={projectOptions} onChange={(value) => setProject(value ?? '')} aria-label="Filter by project" />
      <Segmented<WindowDays> value={days} onChange={setDays} options={[{ label: '7 days', value: 7 }, { label: '30 days', value: 30 }, { label: '90 days', value: 90 }]} />
      {data && <Text className="pm-performance__freshness" type="secondary">Updated {appDate(data.generated_at).format('DD MMM, h:mm A')} ET</Text>}
    </div>
    {error && <Alert type="error" showIcon title="Performance data unavailable" description={error} />}
    {loading && !data ? <ContentLoader label="Loading project performance" minHeight={480} /> : data && <div className={`pm-performance__content${loading ? ' is-refreshing' : ''}`}>
      <section className="pm-metric-grid" aria-label="Project quality metrics">
        <PerformanceMetric title="Evaluations" value={metric?.evaluated ?? 0} detail={`${metric?.scored ?? 0} received a numeric score`} icon={<FileSearchOutlined />} tone="primary" />
        <PerformanceMetric title="Average QA score" value={metric?.average_score ?? 0} suffix="%" detail={metric?.average_score === null ? 'No scored reports in this period' : 'Across scored evaluations'} icon={<CheckCircleOutlined />} tone={scoreTone(metric?.average_score ?? null)} />
        <PerformanceMetric title="Critical failure rate" value={metric?.critical_rate ?? 0} suffix="%" detail={`${metric?.critical ?? 0} critical evaluation${metric?.critical === 1 ? '' : 's'}`} icon={<SafetyCertificateOutlined />} tone={(metric?.critical_rate ?? 0) > 0 ? 'danger' : 'success'} />
        <PerformanceMetric title="Below benchmark" value={metric?.below_benchmark_rate ?? 0} suffix="%" detail={`${metric?.below_benchmark ?? 0} scored below 85%`} icon={<WarningOutlined />} tone={(metric?.below_benchmark_rate ?? 0) > 20 ? 'warning' : 'neutral'} />
      </section>
      <Card className="pm-trend-card" classNames={{ body: 'pm-trend-card__body' }} title={<div className="pm-card-title"><strong>Quality trend</strong><small>Daily average score with evaluation volume</small></div>}><QualityTrend data={data.trend} /></Card>
      <Card className="pm-team-card" title={<div className="pm-card-title"><strong>Team comparison</strong><small>Use volume and risk together when prioritizing follow-up</small></div>} extra={<Button type="link" icon={<ArrowRightOutlined />} iconPlacement="end" onClick={() => navigate('/queue')}>Open reports</Button>}>
        <Table rowKey="id" columns={columns} dataSource={data.teams} pagination={false} size="small" scroll={{ x: 820 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No team evaluations in this period" /> }} />
      </Card>
    </div>}
  </div>;
}
