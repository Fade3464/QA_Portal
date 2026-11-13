import {
  ApartmentOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Empty,
  Segmented,
  Space,
  Statistic,
  Tag,
  Tree,
  Typography,
  type TreeProps,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ContentLoader } from '../components/LoadingStates';
import { api } from '../lib/api';

const { Title, Text } = Typography;

type WindowKey = 'today' | '6h' | '12h' | 'yesterday' | '7d' | 'month';

interface ObservabilityListRow {
  name: string;
  count: number;
}

interface ObservabilityIngroup {
  name: string;
  sales: number;
  lists: ObservabilityListRow[];
}

interface ObservabilityError {
  message: string;
  count: number;
}

interface ObservabilityDialer {
  id: string;
  name: string;
  sales: number;
  error_count: number;
  ingroups: ObservabilityIngroup[];
  errors: ObservabilityError[];
}

interface ObservabilityResponse {
  window: {
    key: WindowKey;
    label: string;
    from: string;
    to: string;
    timezone: string;
  };
  totals: {
    sales: number;
    dialers: number;
    errors: number;
  };
  dialers: ObservabilityDialer[];
  generated_at: string;
}

const windowOptions: Array<{ label: string; value: WindowKey }> = [
  { label: 'Today', value: 'today' },
  { label: '6 hrs', value: '6h' },
  { label: '12 hrs', value: '12h' },
  { label: 'Yesterday', value: 'yesterday' },
  { label: '7 days', value: '7d' },
  { label: 'This month', value: 'month' },
];

function CountTitle({ label, count, tone = 'default' }: { label: string; count: number; tone?: 'default' | 'error' }) {
  return (
    <span className="dialer-tree-title">
      <span>{label}</span>
      <Tag color={tone === 'error' ? 'error' : undefined}>{count.toLocaleString()}</Tag>
    </span>
  );
}

export function DialerObservabilityPage() {
  const [windowKey, setWindowKey] = useState<WindowKey>('today');
  const [data, setData] = useState<ObservabilityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await api<ObservabilityResponse>(`/api/v1/dashboard/observability/?window=${encodeURIComponent(windowKey)}`);
      setData(result);
    } catch {
      setError('Dialer observability could not be loaded. Check the connection and try again.');
    } finally {
      setLoading(false);
    }
  }, [windowKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const treeData = useMemo<TreeProps['treeData']>(() => {
    return (data?.dialers ?? []).map((dialer) => {
      const ingroupNodes = dialer.ingroups.map((ingroup) => ({
        key: `dialer:${dialer.id}:ingroup:${ingroup.name}`,
        icon: <ApartmentOutlined />,
        title: <CountTitle label={ingroup.name} count={ingroup.sales} />,
        children: ingroup.lists.map((list) => ({
          key: `dialer:${dialer.id}:ingroup:${ingroup.name}:list:${list.name}`,
          icon: <DatabaseOutlined />,
          title: <CountTitle label={list.name} count={list.count} />,
          isLeaf: true,
        })),
      }));

      const errorNode = {
        key: `dialer:${dialer.id}:errors`,
        icon: <WarningOutlined />,
        title: <CountTitle label="Errors" count={dialer.error_count} tone="error" />,
        children: dialer.errors.map((item, index) => ({
          key: `dialer:${dialer.id}:error:${index}`,
          title: <CountTitle label={item.message} count={item.count} tone="error" />,
          isLeaf: true,
        })),
      };

      return {
        key: `dialer:${dialer.id}`,
        title: <CountTitle label={dialer.name} count={dialer.sales} />,
        children: [...ingroupNodes, errorNode],
      };
    });
  }, [data]);

  return (
    <div className="dialer-observability-page page-stack">
      <div className="page-heading dialer-observability-heading">
        <div>
          <Text className="eyebrow">DIALER MANAGER</Text>
          <Title level={2}>Observability</Title>
          <Text type="secondary">Closer SALEs grouped by in-group and the fronter list inferred for each call.</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>Refresh</Button>
      </div>

      <Card className="dialer-observability-filter-card">
        <div className="dialer-observability-filter-row">
          <div>
            <Text strong>Time window</Text>
            <Text type="secondary" className="dialer-observability-filter-copy">SALE disposition time</Text>
          </div>
          <Segmented
            options={windowOptions}
            value={windowKey}
            onChange={(value) => setWindowKey(value as WindowKey)}
          />
        </div>
      </Card>

      {error && <Alert type="error" showIcon message={error} action={<Button size="small" onClick={() => void load()}>Retry</Button>} />}

      {loading && !data ? <ContentLoader label="Loading dialer observability" /> : (
        <>
          <div className="dialer-observability-stats">
            <Card><Statistic title="SALEs" value={data?.totals.sales ?? 0} /></Card>
            <Card><Statistic title="Closer dialers" value={data?.totals.dialers ?? 0} /></Card>
            <Card><Statistic title="Errors" value={data?.totals.errors ?? 0} valueStyle={(data?.totals.errors ?? 0) ? { color: 'var(--qa-danger, #cf1322)' } : undefined} /></Card>
          </div>

          <Card className="dialer-observability-tree-card">
            <div className="dialer-observability-tree-head">
              <div>
                <Title level={4}>Closer SALE tree</Title>
                <Text type="secondary">Expand a closer dialer to inspect its in-groups and inferred list names.</Text>
              </div>
              {data && (
                <Space size={6} wrap>
                  <Tag>{data.window.label}</Tag>
                  <Tag>{data.window.timezone}</Tag>
                </Space>
              )}
            </div>
            {treeData?.length ? (
              <Tree
                className="dialer-observability-tree"
                treeData={treeData}
                showLine
                showIcon
                blockNode
                selectable={false}
              />
            ) : (
              <Empty description={`No eligible closer SALEs for ${data?.window.label.toLowerCase() ?? 'this window'}.`} />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
