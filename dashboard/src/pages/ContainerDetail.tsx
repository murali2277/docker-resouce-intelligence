import { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { api, type ContainerMetrics, type Recommendation, type ForecastData } from '../api/client';
import { Spinner, MetricBar } from '../components/MetricsCard';
import { usePolling } from '../hooks/usePolling';
import { fmtBytes } from '../utils/format';


function TrendChart({ container, metric }: { container: ContainerMetrics; metric: 'cpu' | 'memory' }) {
  // We have 4 moving-average points — plot them as a mini trend snapshot
  const data =
    metric === 'cpu'
      ? [
          { t: 'now',  v: container.cpu_percent },
          { t: '5m',   v: container.cpu_percent_5m },
          { t: '15m',  v: container.cpu_percent_15m },
          { t: '60m',  v: container.cpu_percent_60m },
        ]
      : [
          { t: 'now',  v: container.memory_percent },
          { t: '5m',   v: container.memory_percent_5m },
          { t: '15m',  v: container.memory_percent_15m },
          { t: '60m',  v: container.memory_percent_60m },
        ];

  const color = metric === 'cpu' ? '#00d4ff' : '#00e5a0';

  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,150,255,0.07)" />
        <XAxis dataKey="t" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
        <YAxis domain={[0, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} unit="%" />
        <Tooltip
          contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-accent)', borderRadius: 8 }}
          labelStyle={{ color: 'var(--text-primary)', fontWeight: 600 }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Line
          type="monotone"
          dataKey="v"
          name={metric === 'cpu' ? 'CPU %' : 'Memory %'}
          stroke={color}
          strokeWidth={2}
          dot={{ fill: color, r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

interface ContainerDetailProps {
  container: ContainerMetrics;
  onClose: () => void;
}

export default function ContainerDetail({ container, onClose }: ContainerDetailProps) {
  const [forecast, setForecast] = useState<ForecastData | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  // Recommendation: fetched from the list and filtered client-side by container_id
  const { data: recData } = usePolling(() => api.recommendations(), 60_000);
  const rec: Recommendation | undefined = recData?.recommendations.find(
    r => r.container_id === container.container_id,
  );

  useEffect(() => {
    let cancelled = false;
    setForecastLoading(true);
    setForecastError(null);
    api.forecast(container.container_id, 24, 'memory_percent')
      .then(f => { if (!cancelled) { setForecast(f); } })
      .catch(e => { if (!cancelled) { setForecastError(e instanceof Error ? e.message : 'Forecast unavailable'); } })
      .finally(() => { if (!cancelled) setForecastLoading(false); });
    return () => { cancelled = true; };
  }, [container.container_id]);

  const confidenceBadge = (tier: string) => {
    const map: Record<string, string> = { high: 'badge-success', medium: 'badge-info', low: 'badge-warning' };
    return map[tier] ?? 'badge-neutral';
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(5,11,24,0.88)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={onClose}
    >
      {/* Panel — stop propagation so clicking inside doesn't close */}
      <div
        className="card"
        style={{
          width: '100%', maxWidth: 860, maxHeight: '90vh',
          overflowY: 'auto', padding: 28,
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
              {container.is_anomaly && <span title={container.anomaly_type ?? ''} style={{ marginRight: 8 }}>⚠️</span>}
              {container.container_name}
            </div>
            <div style={{ fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>
              {container.container_id}
            </div>
          </div>
          <button
            id="container-detail-close"
            onClick={onClose}
            style={{
              background: 'var(--bg-glass)', border: '1px solid var(--border-glass)',
              borderRadius: 8, color: 'var(--text-muted)',
              padding: '6px 14px', cursor: 'pointer', fontSize: 13,
            }}
          >
            ✕ Close
          </button>
        </div>

        {/* Anomaly banner */}
        {container.is_anomaly && container.anomaly_type && (
          <div className="badge badge-critical" style={{ marginBottom: 16, display: 'inline-block' }}>
            🔴 Anomaly: {container.anomaly_type.replace(/_/g, ' ')}
          </div>
        )}

        {/* Current stats row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12, marginBottom: 24 }}>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>CPU Usage</div>
            <MetricBar label="Now" value={container.cpu_percent} />
            <MetricBar label="5m avg" value={container.cpu_percent_5m} />
            <MetricBar label="15m avg" value={container.cpu_percent_15m} />
            <MetricBar label="60m avg" value={container.cpu_percent_60m} />
          </div>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Memory Usage</div>
            <MetricBar label="Now" value={container.memory_percent} />
            <MetricBar label="5m avg" value={container.memory_percent_5m} />
            <MetricBar label="15m avg" value={container.memory_percent_15m} />
            <MetricBar label="60m avg" value={container.memory_percent_60m} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
              Growth: {container.memory_growth_rate_5m.toFixed(2)}%/min (5m)
            </div>
          </div>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>System & I/O</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Network RX / TX</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent-cyan)' }}>
                  {fmtBytes(container.net_io_in)} / {fmtBytes(container.net_io_out)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Disk Read / Write</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent-cyan)' }}>
                  {fmtBytes(container.block_io_read)} / {fmtBytes(container.block_io_write)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Processes (PIDs)</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {container.pids ?? 'N/A'}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 60m trend charts */}
        <div className="section-header" style={{ marginBottom: 12 }}>
          <div className="section-title">60-Minute Moving Average Trend</div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 28 }}>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>CPU %</div>
            <TrendChart container={container} metric="cpu" />
          </div>
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>Memory %</div>
            <TrendChart container={container} metric="memory" />
          </div>
        </div>

        {/* Recommendation */}
        <div className="section-header" style={{ marginBottom: 12 }}>
          <div className="section-title">Resource Recommendation</div>
        </div>
        {rec ? (
          <div className="card" style={{ padding: 18, marginBottom: 24 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px,1fr))', gap: 16 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>CPU Limit (rec)</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent-cyan)' }}>
                  {rec.recommended_cpu_pct.toFixed(1)}%
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>p95 {rec.p95_cpu.toFixed(1)}%</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Memory Limit (rec)</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--accent-green)' }}>
                  {fmtBytes(rec.recommended_memory_bytes)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  p95 {fmtBytes(rec.p95_memory_bytes)} ({rec.p95_memory_pct.toFixed(1)}%)
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Confidence</div>
                <span className={`badge ${confidenceBadge(rec.confidence_tier)}`}>
                  {rec.confidence_tier}
                </span>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                  {rec.sample_count.toLocaleString()} samples · {rec.lookback_days}d lookback
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Memory Trend</div>
                {rec.is_memory_leak ? (
                  <span className="badge badge-critical">📈 Leak +{rec.memory_leak_slope_pct_per_hour.toFixed(2)}%/hr</span>
                ) : (
                  <span className="badge badge-success">✓ Stable</span>
                )}
                {rec.is_idle && (
                  <div style={{ marginTop: 6 }}>
                    <span className="badge badge-neutral">😴 Idle — {rec.idle_recommendation}</span>
                  </div>
                )}
              </div>
            </div>
            {rec.data_completeness && (
              <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                Data: {rec.data_completeness}
                {rec.computed_at && ` · computed ${new Date(rec.computed_at).toLocaleTimeString()}`}
              </div>
            )}
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 24, padding: '12px 0' }}>
            No recommendation available — need at least 10 historical samples.
          </div>
        )}

        {/* Forecast */}
        <div className="section-header" style={{ marginBottom: 12 }}>
          <div className="section-title">24h Memory Forecast</div>
        </div>
        {forecastLoading && <Spinner />}
        {forecastError && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 0' }}>
            {forecastError}
          </div>
        )}
        {forecast && !forecastLoading && (
          <div className="card" style={{ padding: 18 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px,1fr))', gap: 16 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Current</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)' }}>
                  {forecast.current_value.toFixed(1)}%
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>In 24h (predicted)</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--accent-purple)' }}>
                  {forecast.predicted_value.toFixed(1)}%
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  CI [{forecast.confidence_low.toFixed(1)}, {forecast.confidence_high.toFixed(1)}]
                </div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Method</div>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  {forecast.method_used.replace('_', ' ')}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                  {forecast.sample_count} samples
                </div>
              </div>
            </div>
          </div>
        )}
        {!forecast && !forecastLoading && !forecastError && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', padding: '4px 0' }}>
            Fetching forecast…
          </div>
        )}
      </div>
    </div>
  );
}
