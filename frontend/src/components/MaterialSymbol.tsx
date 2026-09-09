type MaterialSymbolProps = {
  name: string;
  className?: string;
  label?: string;
};

export function MaterialSymbol({ name, className = '', label }: MaterialSymbolProps) {
  return (
    <span
      className={`material-symbol ${className}`.trim()}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
    >
      {name}
    </span>
  );
}
