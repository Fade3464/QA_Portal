interface PortalLoaderProps {
  label?: string;
  compact?: boolean;
}

export function PortalLoader({ label = 'Preparing your workspace…', compact = false }: PortalLoaderProps) {
  return (
    <div className={`portal-loader${compact ? ' portal-loader--compact' : ''}`} role="status" aria-live="polite">
      <div className="portal-loader__stage" aria-hidden="true">
        <span className="portal-loader__orbit portal-loader__orbit--outer"><i /><i /><i /></span>
        <span className="portal-loader__orbit portal-loader__orbit--inner"><i /><i /></span>
        <span className="portal-loader__core">Q</span>
      </div>
      <div className="portal-loader__copy">
        <strong>{label}</strong>
        <span className="portal-loader__signal" aria-hidden="true"><i /><i /><i /><i /><i /></span>
      </div>
    </div>
  );
}
