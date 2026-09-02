export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-mark ${compact ? 'brand-mark--compact' : ''}`} aria-label="QA Portal">
      <span className="brand-mark__glyph">Q</span>
      {!compact && (
        <span className="brand-mark__copy">
          <strong>QA Portal</strong>
          <small>Quality operations</small>
        </span>
      )}
    </div>
  );
}

