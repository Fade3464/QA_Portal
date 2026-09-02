import { ArrowLeftOutlined, BuildOutlined } from '@ant-design/icons';
import { Button, Result } from 'antd';
import { useLocation } from 'react-router-dom';

const names: Record<string, string> = { '/queue': 'Review queue', '/team': 'Team performance', '/insights': 'Quality insights' };

export function PlaceholderPage() {
  const location = useLocation();
  return <div className="placeholder-page"><Result icon={<BuildOutlined />} title={`${names[location.pathname] ?? 'Workspace'} is ready for the next phase`} subTitle="The navigation, permissions, and domain foundation are in place. We’ll build this workflow on top of real call data next." extra={<Button type="primary" href="/" icon={<ArrowLeftOutlined />}>Back to command center</Button>} /></div>;
}
