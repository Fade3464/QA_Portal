import { DatabaseOutlined, DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { Alert, Button, Card, Empty, Segmented, Select, Space, Statistic, Table, Tag, Typography, type TableProps } from 'antd';
import { useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { appDate } from '../lib/datetime';
import { ContentLoader } from './LoadingStates';

type Kind = 'read' | 'write' | 'other';
type Window = '1h' | '24h' | '7d' | '30d';
type Source = 'all' | 'http' | 'worker';
type Metric = {
  count: number; average_ms: number | null; p95_upper_ms: number | null;
  p95_overflow: boolean; max_ms: number | null; queries_per_second: number; errors: number; slow: number;
};
type Series = Record<Kind, Metric>;
type SlowOperation = { at: string; source: string; kind: Kind; operation: string; duration_ms: number; failed: boolean; workload: string };
type Snapshot = {
  status: string; engine: string; captured_at?: string; cache_hit_percent?: number | null;
  connections?: number; active_connections?: number; lock_waiters?: number; commits?: number;
  rollbacks?: number; deadlocks?: number; blocks_read?: number; blocks_hit?: number;
  rows_returned?: number; rows_fetched?: number;
  rows_inserted?: number; rows_updated?: number; rows_deleted?: number; temp_bytes?: number;
  io_timing_enabled?: boolean; block_read_ms?: number | null; block_write_ms?: number | null; stats_reset_at?: string | null;
};
type Performance = {
  status: 'collecting' | 'disabled' | 'unavailable'; reason?: string; generated_at: string;
  start?: string; end?: string; resolution_seconds?: number; first_observed_at?: string | null;
  last_http_at?: string | null; last_worker_at?: string | null;
  summary?: Series; previous?: Series; latency_change_percent?: Record<Kind, number | null>;
  observed_buckets?: number; total_buckets?: number; slow_threshold_ms?: number;
  trend?: (Series & { at: string; observed: boolean })[]; slow_operations?: SlowOperation[]; postgres: Snapshot;
};

const { Text } = Typography;
const formatMs = (value: number | null | undefined) => value == null ? '—' : `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ms`;
const formatCount = (value: number | undefined) => value == null ? '—' : value.toLocaleString();

function exportHistory(data: Performance) {
  const cell = (value: unknown) => {
    const text = String(value ?? '');
    return `"${(/^[\s]*[=+\-@]/.test(text) ? `'${text}` : text).replaceAll('"', '""')}"`;
  };
  const header = ['Interval UTC', 'Observed', 'Operation', 'Queries', 'Average ms', 'P95 upper bound ms', 'P95 above bound', 'Max ms', 'Queries/s', 'Errors', 'Slow queries'];
  const rows = (data.trend ?? []).flatMap((point) => (['read', 'write', 'other'] as Kind[]).map((kind) => {
    const metric = point[kind];
    return [point.at, point.observed, kind, metric.count, metric.average_ms, metric.p95_upper_ms, metric.p95_overflow, metric.max_ms, metric.queries_per_second, metric.errors, metric.slow];
  }));
  const blob = new Blob([[header, ...rows].map((row) => row.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `calllens-database-${data.generated_at.replaceAll(':', '-')}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function TrendChart({ data, mode }: { data: NonNullable<Performance['trend']>; mode: 'latency' | 'volume' }) {
  const [focus, setFocus] = useState<number | null>(null);
  const value = (point: typeof data[number], kind: 'read' | 'write') => mode === 'latency' ? point[kind].average_ms : (point.observed ? point[kind].queries_per_second : null);
  const available = data.some((point) => point.observed && (point.read.count || point.write.count));
  if (!available) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No read/write samples in this period" />;
  const width = 800, height = 240, left = 58, right = 18, top = 18, bottom = 34;
  const ceiling = Math.max(1, ...data.flatMap((point) => [value(point, 'read') ?? 0, value(point, 'write') ?? 0])) * 1.1;
  const x = (index: number) => left + index / Math.max(1, data.length - 1) * (width - left - right);
  const y = (amount: number) => top + (1 - amount / ceiling) * (height - top - bottom);
  const paths = (kind: 'read' | 'write') => {
    let drawing = false;
    return data.map((point, index) => {
      const amount = value(point, kind);
      if (amount === null || !point.observed) { drawing = false; return ''; }
      const command = drawing ? 'L' : 'M';
      drawing = true;
      return `${command}${x(index)} ${y(amount)}`;
    }).join(' ');
  };
  const active = focus === null ? null : data[focus];
  return <div className="db-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={mode === 'latency' ? 'Read and write average query latency over time' : 'Read and write queries per second over time'} onMouseLeave={() => setFocus(null)}>
      {[0, 0.5, 1].map((fraction) => <g key={fraction}><line x1={left} x2={width - right} y1={y(ceiling * fraction)} y2={y(ceiling * fraction)} className="db-chart__grid" /><text x={left - 8} y={y(ceiling * fraction) + 4} textAnchor="end">{(ceiling * fraction).toFixed(ceiling > 10 ? 0 : 2)}</text></g>)}
      <path d={paths('read')} className="db-chart__read" /><path d={paths('write')} className="db-chart__write" />
      {(['read', 'write'] as const).map((kind) => data.map((point, index) => value(point, kind) != null && point.observed ? <circle key={`${kind}:${point.at}`} cx={x(index)} cy={y(value(point, kind)!)} r={2} className={`db-chart__${kind}`} /> : null))}
      {data.map((point, index) => <rect key={point.at} x={x(index) - (width - left - right) / Math.max(1, data.length - 1) / 2} y={top} width={(width - left - right) / Math.max(1, data.length - 1)} height={height - top - bottom} fill="transparent" onMouseEnter={() => setFocus(index)}><title>{appDate(point.at).format('DD MMM, HH:mm')} ET · Read {value(point, 'read') ?? '—'} · Write {value(point, 'write') ?? '—'}</title></rect>)}
      {active && focus !== null && <line x1={x(focus)} x2={x(focus)} y1={top} y2={height - bottom} className="db-chart__cursor" />}
      {[0, Math.floor((data.length - 1) / 2), data.length - 1].map((index) => <text key={index} x={x(index)} y={height - 8} textAnchor={index === 0 ? 'start' : index === data.length - 1 ? 'end' : 'middle'}>{appDate(data[index].at).format('DD MMM HH:mm')}</text>)}
    </svg>
    <div className="db-chart__legend"><span className="db-read-dot">Reads</span><span className="db-write-dot">Writes</span><small>{active ? `${appDate(active.at).format('DD MMM, HH:mm')} ET · Reads ${value(active, 'read')?.toFixed(2) ?? '—'} · Writes ${value(active, 'write')?.toFixed(2) ?? '—'} ${mode === 'latency' ? 'ms' : '/s'}` : mode === 'latency' ? 'Lower latency is better · milliseconds' : 'Average query rate · queries/second'}</small></div>
  </div>;
}

function OperationCard({ kind, data }: { kind: 'read' | 'write'; data: Performance }) {
  const metric = data.summary?.[kind];
  const change = data.latency_change_percent?.[kind];
  return <Card className={`db-operation db-operation--${kind}`}>
    <div className="db-operation__heading"><Text type="secondary">{kind === 'read' ? 'Read latency' : 'Write latency'}</Text>{change != null && <Tag className="db-change-tag" color={change > 0 ? 'orange' : change < 0 ? 'green' : 'default'}>{change > 0 ? '+' : ''}{change}% vs previous period</Tag>}</div>
    <Statistic value={metric?.average_ms ?? '—'} precision={2} suffix={metric?.average_ms != null ? 'ms' : undefined} />
    <div className="db-operation__stats"><span><small>Queries</small><strong>{formatCount(metric?.count)}</strong></span><span><small>P95 (approx.)</small><strong>{metric?.p95_upper_ms == null ? '—' : `${metric.p95_overflow ? '>' : '≤'} ${formatMs(metric.p95_upper_ms)}`}</strong></span><span><small>Maximum</small><strong>{formatMs(metric?.max_ms)}</strong></span><span><small>Window avg.</small><strong>{metric ? `${metric.queries_per_second}/s` : '—'}</strong></span></div>
  </Card>;
}

export function DatabasePerformance({ active }: { active: boolean }) {
  const [windowSize, setWindowSize] = useState<Window>('1h');
  const [source, setSource] = useState<Source>('all');
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Performance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer = 0;
    let pending = false;
    const load = async () => {
      if (pending || controller.signal.aborted || document.hidden) return;
      pending = true;
      window.clearTimeout(timer);
      setLoading(true);
      try {
        const result = await api<Performance>(`/api/v1/administration/database-performance/?window=${windowSize}&source=${source}`, { signal: controller.signal });
        if (!controller.signal.aborted) { setData(result); setError(''); }
      } catch (issue) {
        if (!controller.signal.aborted) setError(issue instanceof ApiError ? issue.message : 'Database metrics could not be loaded.');
      } finally {
        pending = false;
        if (!controller.signal.aborted) { setLoading(false); timer = window.setTimeout(() => void load(), 30_000); }
      }
    };
    const onVisibility = () => { if (!document.hidden) void load(); };
    document.addEventListener('visibilitychange', onVisibility);
    const frame = window.requestAnimationFrame(() => void load());
    return () => { controller.abort(); window.clearTimeout(timer); window.cancelAnimationFrame(frame); document.removeEventListener('visibilitychange', onVisibility); };
  }, [active, refresh, source, windowSize]);

  const columns: TableProps<SlowOperation>['columns'] = [
    { title: 'Time (ET)', dataIndex: 'at', width: 200, render: (value: string) => appDate(value).format('DD MMM, HH:mm:ss.SSS') },
    { title: 'Workload', dataIndex: 'workload', ellipsis: true },
    { title: 'Source', dataIndex: 'source', width: 110, render: (value: string) => value === 'worker' ? 'Worker' : 'Web' },
    { title: 'Operation', dataIndex: 'operation', width: 120 },
    { title: 'Duration', dataIndex: 'duration_ms', width: 140, align: 'right', sorter: (a, b) => a.duration_ms - b.duration_ms, render: formatMs },
    { title: 'Result', dataIndex: 'failed', width: 110, render: (value: boolean) => <Tag color={value ? 'red' : 'default'}>{value ? 'Failed' : 'Completed'}</Tag> },
  ];
  const pg = data?.postgres;
  const hasData = !!data?.summary && Object.values(data.summary).some((metric) => metric.count > 0);
  const totalErrors = Object.values(data?.summary ?? {}).reduce((sum, metric) => sum + metric.errors, 0);
  const totalSlow = Object.values(data?.summary ?? {}).reduce((sum, metric) => sum + metric.slow, 0);
  return <div className="db-performance page-stack">
    <div className="db-toolbar"><Space className="db-toolbar-controls" wrap><Segmented<Window> value={windowSize} onChange={setWindowSize} options={[{ label: '1 hour', value: '1h' }, { label: '24 hours', value: '24h' }, { label: '7 days', value: '7d' }, { label: '30 days', value: '30d' }]} /><Select<Source> className="db-source-select" value={source} onChange={setSource} options={[{ label: 'All workloads', value: 'all' }, { label: 'Web requests', value: 'http' }, { label: 'Background workers', value: 'worker' }]} aria-label="Database workload source" /></Space><Space><Button icon={<DownloadOutlined />} disabled={!hasData || loading} onClick={() => data && exportHistory(data)}>Export trends</Button><Button icon={<ReloadOutlined />} loading={loading} onClick={() => setRefresh((value) => value + 1)}>Refresh</Button></Space></div>
    {error && <Alert type="error" showIcon title={error} />}
    {loading && data && <Text type="secondary" role="status">Updating measurements…</Text>}
    {loading && !data ? <ContentLoader label="Loading database performance" minHeight={440} /> : data && <div className={`db-results page-stack${loading ? ' db-results--updating' : ''}`} aria-busy={loading}>
      {data.status !== 'collecting' && <Alert type="warning" showIcon title={data.status === 'disabled' ? 'Database telemetry is disabled' : 'Telemetry is temporarily unavailable'} description={data.reason} />}
      {data.status === 'collecting' && !hasData && <Alert type="info" showIcon title="Waiting for the first completed interval" description="Performance history starts after deployment. Web requests and worker tasks contribute automatically." />}
      <div className="db-summary"><OperationCard kind="read" data={data} /><OperationCard kind="write" data={data} /><Card className="db-health"><div className="db-operation__heading"><Text type="secondary">Reliability</Text><DatabaseOutlined /></div><Statistic title="SQL errors" value={data.summary ? totalErrors : '—'} /><div className="db-health__details"><span>{formatCount(data.summary ? totalSlow : undefined)} slow queries ≥ {data.slow_threshold_ms ?? 100} ms</span><span>{formatCount(data.summary?.other.count)} transaction / other statements</span></div></Card></div>
      <div className="db-chart-grid"><Card title="Query latency"><TrendChart data={data.trend ?? []} mode="latency" /></Card><Card title="Query throughput"><TrendChart data={data.trend ?? []} mode="volume" /></Card></div>
      <div className="db-coverage"><Text type="secondary">Completed intervals through {data.end ? `${appDate(data.end).format('DD MMM, HH:mm')} ET` : '—'} · Updated {appDate(data.generated_at).format('HH:mm:ss')} ET</Text><Text type="secondary">Web last observed: {data.last_http_at ? `${appDate(data.last_http_at).format('DD MMM, HH:mm:ss')} ET` : 'Waiting'} · Worker: {data.last_worker_at ? `${appDate(data.last_worker_at).format('DD MMM, HH:mm:ss')} ET` : 'Waiting'}</Text></div>
      <Card title="PostgreSQL health" extra={<Tag>{pg?.engine ?? 'Database'}</Tag>}>
        {pg?.status === 'available' ? <><div className="db-pg-grid">{[
          ['Cache hit rate', pg.cache_hit_percent == null ? '—' : `${pg.cache_hit_percent}%`],
          ['Connections', formatCount(pg.connections)], ['Active queries', formatCount(pg.active_connections)],
          ['Lock waiters', formatCount(pg.lock_waiters)], ['Deadlocks', formatCount(pg.deadlocks)],
          ['Commits / rollbacks', `${formatCount(pg.commits)} / ${formatCount(pg.rollbacks)}`],
          ['Blocks read / cached', `${formatCount(pg.blocks_read)} / ${formatCount(pg.blocks_hit)}`],
          ['Rows returned / fetched', `${formatCount(pg.rows_returned)} / ${formatCount(pg.rows_fetched)}`],
          ['Rows inserted / updated / deleted', `${formatCount(pg.rows_inserted)} / ${formatCount(pg.rows_updated)} / ${formatCount(pg.rows_deleted)}`],
          ['Temporary data', pg.temp_bytes == null ? '—' : `${(pg.temp_bytes / 1048576).toFixed(1)} MB`],
          ['Block read / write time', `${formatMs(pg.block_read_ms)} / ${formatMs(pg.block_write_ms)}`],
        ].map(([label, value]) => <div key={label}><Text type="secondary">{label}</Text><strong>{value}</strong></div>)}</div><Text type="secondary">Server counters since {pg.stats_reset_at ? `${appDate(pg.stats_reset_at).format('DD MMM YYYY, HH:mm')} ET` : 'statistics reset'} · Snapshot {pg.captured_at ? `${appDate(pg.captured_at).format('HH:mm:ss')} ET` : '—'}{!pg.io_timing_enabled && ' · Block timing is disabled on PostgreSQL'}</Text></> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={pg?.status === 'unsupported' ? 'Server counters require PostgreSQL; SQL telemetry still works with this database.' : 'PostgreSQL counters could not be read.'} />}
      </Card>
      <Card title="Slow and failed operations" extra={<Text type="secondary">Up to 200 recent samples</Text>}><Table<SlowOperation> rowKey={(row) => `${row.at}:${row.workload}:${row.operation}:${row.duration_ms}`} columns={columns} dataSource={data.slow_operations ?? []} showSorterTooltip={false} pagination={{ pageSize: 10, showSizeChanger: true }} scroll={{ x: 950 }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No slow or failed samples in this period" /> }} /></Card>
      <details className="db-methodology"><summary>How these measurements work</summary><p>All SQL statements executed in web requests and Celery tasks are timed without storing SQL text, query parameters, user IDs, or credentials. Latency measures the database execute call, including lock waits and the network round trip; result iteration, transaction commit calls, and physical disk bandwidth are outside this measurement.</p><p>P95 is an approximate histogram upper bound. Comparisons use the preceding equal-length period and appear only with at least 20 queries in both periods. A workload or query mix change can affect the comparison. Charts leave gaps where no samples were captured; query throughput is averaged over the selected interval. No synthetic benchmarks are run.</p><p>Minute aggregates are retained for 48 hours and hourly aggregates for 90 days in Redis. Recent slow-operation logs retain up to five samples per request/task and 200 samples overall. Data is refreshed every 30 seconds while this tab is active. Historical data begins at deployment and follows Redis persistence and backup policy.</p></details>
    </div>}
  </div>;
}
