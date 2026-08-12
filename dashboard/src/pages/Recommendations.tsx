import { api, type Recommendation } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

function fmtBytes(b: number): string {
  if (b >= 1e9) return `${(b / 1e9).toFixed(2)} GB`;
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  return `${b} B`;
}

function confidenceBadge(tier: string): string {
  const m: Record<string, string> = { high: 'badge-success', medium: 'badge-info', low: 'badge-warning' };
  return m[tier] ?? 'badge-neutral';
}

function RecRow({ rec }: { rec: Recommendation }) {
  return (
    <tr>
      <td>
        <span style={{ fontWeight: 600 }}>{rec.container_name}</span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {rec.container_id}
        </span>
      </td>
      <td>
        <span style={{ color: 'var(--accent-cyan)', fontWeight: 700 }}>
          {rec.recommended_cpu_pct.toFixed(1)}%
        </span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          p95 {rec.p95_cpu.toFixed(1)}%
        </span>
      </td>
      <td>
        <span style={{ color: 'var(--accent-green)', fontWeight: 700 }}>
          {fmtBytes(rec.recommended_memory_bytes)}
        </span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          p95 {fmtBytes(rec.p95_memory_bytes)} ({rec.p95_memory_pct.toFixed(1)}%)
        </span>
      </td>
      <td>
        {/* Confidence tier */}
        <span className={`badge ${confidenceBadge(rec.confidence_tier)}`}>
          {rec.confidence_tier}
        </span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {rec.sample_count.toLocaleString()} samples
        </span>
      </td>
      <td>
        {/* Memory trend + idle */}
        {rec.is_memory_leak ? (
          <span className="badge badge-critical">
            📈 Leak +{rec.memory_leak_slope_pct_per_hour.toFixed(2)}%/hr
          </span>
        ) : (
          <span className="badge badge-success">✓ Stable</span>
        )}
        {rec.is_idle && (
          <div style={{ marginTop: 4 }}>
            <span className="badge badge-neutral">
              😴 {rec.idle_recommendation ?? 'Idle'}
            </span>
          </div>
        )}
      </td>
      <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {rec.lookback_days}d · +{Math.round(rec.safety_margin * 100)}% margin
        {rec.data_completeness && (
          <>
            <br />
            <span style={{ fontSize: 11 }}>{rec.data_completeness}</span>
          </>
        )}
        {rec.computed_at && (
          <>
            <br />
            <span style={{ fontSize: 11 }}>
              cached {new Date(rec.computed_at).toLocaleTimeString()}
            </span>
          </>
        )}
      </td>
    </tr>
  );
}

export default function Recommendations() {
  const { data, loading, error } = usePolling(() => api.recommendations(), 60_000);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Resource Recommendations</div>
        <div className="topbar-meta">
          <div className="refresh-badge">🔄 1 min refresh</div>
          {data && <span>{data.total_count} containers</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            <div
              style={{
                marginBottom: 24,
                padding: '14px 20px',
                background: 'rgba(0,212,255,0.07)',
                border: '1px solid rgba(0,212,255,0.15)',
                borderRadius: 'var(--radius-md)',
                fontSize: 13,
                color: 'var(--text-secondary)',
                lineHeight: 1.6,
              }}
            >
              💡 Recommended limits are computed from <strong>p95 usage over the last 7 days</strong>{' '}
              plus a <strong>+20% safety margin</strong>. Memory leak detection uses 6-hour linear regression.
              Results are served from the background cache (refreshed hourly); click{' '}
              <strong>Forecast</strong> for per-container projections.
            </div>

            <div className="section-header">
              <div className="section-title">Container Limits</div>
              <span className="section-count">{data.recommendations.length} recommendations</span>
            </div>

            {data.recommendations.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">💡</div>
                <div className="empty-title">No recommendations yet</div>
                <div className="empty-sub">
                  Recommendations require at least 10 historical samples per container.
                  They appear after a few minutes of data collection.
                </div>
              </div>
            ) : (
              <div className="card">
                <div className="card-body" style={{ padding: 0 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Container</th>
                        <th>CPU Limit</th>
                        <th>Memory Limit</th>
                        <th>Confidence</th>
                        <th>Memory Trend</th>
                        <th>Data</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recommendations.map(r => (
                        <RecRow key={r.container_id} rec={r} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
