interface BrandMarkProps {
  compact?: boolean;
  contrast?: boolean;
}

export function BrandMark({ compact = false, contrast = false }: BrandMarkProps) {
  return (
    <div
      className={`brand-mark${compact ? ' brand-mark--compact' : ''}${contrast ? ' brand-mark--contrast' : ''}`}
      role="img"
      aria-label="CallLens"
    >
      <span className="brand-mark__icon-layer" aria-hidden="true">
        <img
          className="brand-mark__icon"
          src="/brand/calllens-icon.png"
          alt=""
          width="1254"
          height="1254"
          decoding="async"
        />
      </span>
      <span className="brand-mark__wordmark-layer" aria-hidden="true">
        <img
          className="brand-mark__wordmark brand-mark__wordmark--light"
          src="/brand/calllens-wordmark.png"
          alt=""
          width="2172"
          height="724"
          decoding="async"
        />
        <img
          className="brand-mark__wordmark brand-mark__wordmark--dark"
          src="/brand/calllens-wordmark-dark.png"
          alt=""
          width="2172"
          height="724"
          decoding="async"
        />
      </span>
    </div>
  );
}
