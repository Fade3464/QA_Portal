import { Skeleton, Spin } from 'antd';
import type { CSSProperties } from 'react';

export function ContentLoader({ label = 'Loading', fullPage = false, minHeight = 360 }: { label?: string; fullPage?: boolean; minHeight?: number }) {
  return (
    <div
      className={`content-loader${fullPage ? ' content-loader--page' : ''}`}
      style={fullPage ? undefined : { minHeight }}
      role="status"
      aria-live="polite"
    >
      <Spin size="large" delay={180} percent="auto" description={label} />
    </div>
  );
}

function Line({ width = '100%' }: { width?: CSSProperties['width'] }) {
  return <Skeleton.Input active size="small" block style={{ width }} />;
}

/** Reserved for the call library, where preserving the table geometry prevents layout shift. */
export function TableSkeleton({ rows = 7, columns = 6 }: { rows?: number; columns?: number }) {
  const style = { '--skeleton-columns': columns } as CSSProperties;
  return (
    <div className="table-skeleton" role="status" aria-live="polite" aria-label="Loading call records">
      <div className="table-skeleton__row table-skeleton__row--header" style={style}>{Array.from({ length: columns }, (_, index) => <Line key={index} width={`${52 + (index % 3) * 13}%`} />)}</div>
      {Array.from({ length: rows }, (_, row) => <div className="table-skeleton__row" style={style} key={row}>{Array.from({ length: columns }, (_, column) => <Line key={column} width={`${62 + ((row + column) % 3) * 12}%`} />)}</div>)}
      <div className="table-skeleton__footer"><Line width={126} /><div><Skeleton.Button active size="small" /><Skeleton.Button active size="small" /></div></div>
    </div>
  );
}
