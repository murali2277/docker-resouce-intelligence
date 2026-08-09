import React from 'react';

interface MetricBarProps {
  label: string;
  value: number;
  max?: number;
  color?: string;
}

function getBarColor(pct: number): string {
  if (pct >= 85) return 'var(--accent-red)';
  if (pct >= 65) return 'var(--accent-amber)';
  return 'var(--accent-cyan)';
}

export const MetricBar: React.FC<MetricBarProps> = ({ label, value, max = 100, color }) => {
  const pct = Math.min(100, (value / max) * 100);
  const barColor = color ?? getBarColor(pct);

  return (
    <div className="metric-row">
      <div className="metric-label-row">
        <span className="metric-name">{label}</span>
        <span className="metric-val">{value.toFixed(1)}%</span>
      </div>
      <div className="metric-bar-wrap">
        <div className="metric-bar-track">
          <div
            className="metric-bar-fill"
            style={{ width: `${pct}%`, background: barColor }}
          />
        </div>
      </div>
    </div>
  );
};

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  gradient?: string;
}

export const StatCard: React.FC<StatCardProps> = ({ label, value, sub, gradient }) => (
  <div
    className="card stat-card"
    style={{ '--accent-gradient': gradient } as React.CSSProperties}
  >
    <div className="stat-label">{label}</div>
    <div className="stat-value">{value}</div>
    {sub && <div className="stat-sub">{sub}</div>}
  </div>
);

export const Spinner: React.FC = () => (
  <div className="spinner-wrap">
    <div className="spinner" />
  </div>
);

interface ErrorBannerProps { message: string; }
export const ErrorBanner: React.FC<ErrorBannerProps> = ({ message }) => (
  <div className="error-banner">
    ⚠️ {message}
  </div>
);
