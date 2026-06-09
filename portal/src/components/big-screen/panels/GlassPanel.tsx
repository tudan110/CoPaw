import type { SourceStatus } from "../types.ts";

interface GlassPanelProps {
  title?: string;
  sourceStatus?: SourceStatus;
  className?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

const STATUS_LABEL: Record<SourceStatus, string> = {
  live: "live",
  empty: "empty",
  failed: "failed",
  gap: "gap",
};

export function GlassPanel({
  title,
  sourceStatus,
  className = "",
  children,
  style,
}: GlassPanelProps) {
  return (
    <div className={`bs-gp ${className}`} style={style}>
      {(title || sourceStatus) && (
        <div className="bs-gp-header">
          {title && <span className="bs-gp-title">{title}</span>}
          {sourceStatus && (
            <span className={`bs-gp-badge bs-gp-badge--${sourceStatus}`}>
              {STATUS_LABEL[sourceStatus]}
            </span>
          )}
        </div>
      )}
      <div className="bs-gp-body">{children}</div>
    </div>
  );
}
