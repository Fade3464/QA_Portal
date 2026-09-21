import { ArrowLeftOutlined, BuildOutlined } from '@ant-design/icons';
import { Button, Result } from 'antd';
import { useLocation } from 'react-router-dom';

const names: Record<string, string> = { '/queue': 'Review queue', '/team': 'Team performance', '/insights': 'Quality insights' };

export function PlaceholderPage() {
  const location = useLocation();
  return <div className="placeholder-page"><Result icon={<BuildOutlined />} title={names[location.pathname] ?? 'Workspace'} subTitle="This section is currently under development." extra={<Button type="primary" href="/" icon={<ArrowLeftOutlined />}>Back to command center</Button>} /></div>;
}
