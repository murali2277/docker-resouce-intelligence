import { useState } from 'react';
import { api, type ContainerMetrics } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { StatCard, MetricBar, Spinner, ErrorBanner } from '../components/MetricsCard';
import ContainerDetail from './ContainerDetail';

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export default function Overview() {
  const { intervalMs } = usePollingInterval();
  const { data: health, loading: hLoad, error: hErr } = usePolling(() => api.health(), intervalMs);
  const { data: metrics, loading: mLoad, error: mErr } = usePolling(() => api.metrics(), intervalMs);
  const [selected, setSelected] = useState<ContainerMetrics | null>(null);

  const loading = hLoad || mLoad;
  const error = hErr ?? mErr;

  return (
    <>
      {/* Container detail modal — rendered above everything else */}
      {selected && (
        <ContainerDetail
          container={selected}
          onClose={() => setSelected(null)}
        />
      )}

      <div className="topbar">
        <div className="topbar-title">System Overview</div>
        <div className="topbar-meta">
          <div className="refresh-badge">🔄 Live · {(intervalMs / 1000).toFixed(0)}s</div>
          {health && <span>{new Date(health.timestamp).toLocaleTimeString()}</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !health && <Spinner />}

        {health && (
          <>
            <div className="section-header">
              <div className="section-title">Agent Health</div>
              <span className="badge badge-success">● {health.status}</span>
            </div>

            <div className="stat-grid" style={{ marginBottom: 32 }}>
              <StatCard
                label="Uptime"
                value={fmtUptime(health.uptime_seconds)}
                sub={`v${health.version}`}
                gradient="var(--grad-primary)"
              />
              <StatCard
                label="Metrics Processed"
                value={health.metrics_processed.toLocaleString()}
                sub="total samples stored"
                gradient="var(--grad-success)"
              />
              <StatCard
                label="Alerts Generated"
                value={health.alerts_generated.toLocaleString()}
                sub="policy violations detected"
                gradient="var(--grad-warning)"
              />
              <StatCard
                label="Actions Executed"
                value={health.actions_executed.toLocaleString()}
                sub="throttle / isolate / restart"
                gradient="var(--grad-danger)"
              />
            </div>
          </>
        )}

        {metrics && metrics.containers.length > 0 && (
          <>
            <div className="section-header">
              <div className="section-title">Containers</div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span className="section-count">{metrics.total_count} active</span>
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Click a container for details
                </span>
              </div>
            </div>

            <div className="container-grid">
              {metrics.containers.map(c => (
                <div
                  key={c.container_id}
                  id={`container-card-${c.container_id}`}
                  className={`card container-card ${c.is_anomaly ? 'anomaly-glow' : ''}`}
                  style={{ padding: 20, cursor: 'pointer' }}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelected(c)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setSelected(c); }}
                >
                  <div className="container-name">
                    {c.is_anomaly && <span title={c.anomaly_type ?? ''}>⚠️</span>}
                    {c.container_name}
                    <span className="container-id-tag">{c.container_id}</span>
                  </div>

                  {c.is_anomaly && c.anomaly_type && (
                    <div className="badge badge-critical" style={{ marginBottom: 8, marginTop: 4 }}>
                      🔴 {c.anomaly_type.replace(/_/g, ' ')}
                    </div>
                  )}

                  <MetricBar label="CPU (now)" value={c.cpu_percent} />
                  <MetricBar label="CPU (5m avg)" value={c.cpu_percent_5m} />
                  <MetricBar label="Memory (now)" value={c.memory_percent} />
                  <MetricBar label="Memory (5m avg)" value={c.memory_percent_5m} />

                  <div
                    style={{
                      marginTop: 12,
                      fontSize: 11,
                      color: 'var(--text-muted)',
                      display: 'flex',
                      justifyContent: 'space-between',
                    }}
                  >
                    <span>Growth: {c.memory_growth_rate_5m.toFixed(2)}%/min</span>
                    <span>{new Date(c.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {metrics && metrics.containers.length === 0 && !loading && (
          <div className="empty-state">
            <div className="empty-icon">🐳</div>
            <div className="empty-title">No containers detected</div>
            <div className="empty-sub">Metrics will appear once the DRI agent collects data from running containers.</div>
          </div>
        )}
      </div>
    </>
  );
}
