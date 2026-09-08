import { useState } from 'react';
import { api, type Recommendation } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { Spinner, ErrorBanner } from '../components/MetricsCard';
import { fmtBytes } from '../utils/format';
import {
  IconTrendUp, IconCheck, IconIdle, IconEmptyBox, IconRestart, IconClose,
} from '../components/icons';

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
        {/* CPU — larger tabular-nums */}
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 22,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          color: 'var(--info)',
          lineHeight: 1,
          display: 'block',
        }}>
          {rec.recommended_cpu_pct.toFixed(1)}%
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          p95 {rec.p95_cpu.toFixed(1)}%
        </span>
      </td>
      <td>
        {/* Memory — larger tabular-nums */}
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 22,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
          color: 'var(--ok)',
          lineHeight: 1,
          display: 'block',
        }}>
          {fmtBytes(rec.recommended_memory_bytes)}
        </span>
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
            <IconTrendUp size={11} /> Leak +{rec.memory_leak_slope_pct_per_hour.toFixed(2)}%/hr
          </span>
        ) : (
          <span className="badge badge-success"><IconCheck size={11} /> Stable</span>
        )}
        {rec.is_idle && (
          <div style={{ marginTop: 4 }}>
            <span className="badge badge-neutral">
              <IconIdle size={11} /> {rec.idle_recommendation ?? 'Idle'}
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
  const { intervalMs } = usePollingInterval();
  const recInterval = Math.max(60_000, intervalMs * 6);
  const { data, loading, error } = usePolling(() => api.recommendations(), recInterval);
  const [infoDismissed, setInfoDismissed] = useState(false);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Resource Recommendations</div>
        <div className="topbar-meta">
          <div className="refresh-badge"><IconRestart size={11} /> {(recInterval / 1000).toFixed(0)}s refresh</div>
          {data && <span>{data.total_count} containers</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            {/* Collapsible info strip */}
            {!infoDismissed && (
              <div
                style={{
                  marginBottom: 24,
                  padding: '10px 16px',
                  background: 'rgba(108,142,191,0.06)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  lineHeight: 1.6,
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 12,
                }}
              >
                <span style={{ flex: 1 }}>
                  Recommended limits computed from{' '}
                  <strong style={{ color: 'var(--paper-soft)' }}>p95 usage over the last 7 days</strong>{' '}
                  plus a <strong style={{ color: 'var(--paper-soft)' }}>+20% safety margin</strong>.
                  Memory leak detection uses 6-hour linear regression.
                  Results served from background cache (refreshed hourly).
                </span>
                <button
                  id="rec-info-dismiss"
                  onClick={() => setInfoDismissed(true)}
                  title="Dismiss"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--muted)',
                    cursor: 'pointer',
                    padding: '2px 4px',
                    flexShrink: 0,
                    lineHeight: 1,
                  }}
                >
                  <IconClose size={12} />
                </button>
              </div>
            )}

            <div className="section-header">
              <div className="section-title">Container Limits</div>
              <span className="section-count">{data.recommendations.length} recommendations</span>
            </div>

            {data.recommendations.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon"><IconEmptyBox size={28} /></div>
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
