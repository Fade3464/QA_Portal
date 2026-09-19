import { Button, Result } from 'antd';
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { failed: boolean }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('CallLens render failure', error, info.componentStack);
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="fatal-error">
          <Result
            status="500"
            title="This view could not be displayed"
            subTitle="Your data is safe. Reload the portal to restore the interface."
            extra={<Button type="primary" onClick={() => window.location.reload()}>Reload portal</Button>}
          />
        </main>
      );
    }
    return this.props.children;
  }
}
