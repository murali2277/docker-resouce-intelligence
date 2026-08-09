import { useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts';
import { api, type ForecastData, type ContainerMetrics } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

const HORIZON_OPTIONS = [6, 12, 24, 48, 72, 168];
const METRIC_OPTIONS: { value: string; label: string }[] = [
  { value: 'memory_percent', label: 'Memory %' },
  { value: 'cpu_percent',    label: 'CPU %' },
];

function buildChartData(
  containers: ContainerMetrics[],
  selectedId: string,
  forecast: ForecastData | null,
): { name: string; actual?: number; predicted?: number; low?: number; high?: number }[] {
  const container = containers.find(c => c.container_id === selectedId);
  if (!container) return [];

  // Provide the 5 historical moving average points we have
  const history = [
    { name: 'now', actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent : container.memory_percent },
    { name: '5m avg', actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_5m : container.memory_percent_5m },
    { name: '15m avg', actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_15m : container.memory_percent_15m },
    { name: '60m avg', actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_60m : container.memory_percent_60m },
  ];

  if (!forecast) return history;

  const horizonLabel = `+${forecast.horizon_hours}h`;
  return [
    ...history,
    {
      name: horizonLabel,
      predicted: forecast.predicted_value,
      low: forecast.confidence_low,
      high: forecast.confidence_high,
    },
  ];
}

export default function Forecast() {
  const [selectedId, setSelectedId] = useState<string>('');
  const [horizonHours, setHorizonHours] = useState(24);
  const [metric, setMetric] = useState('memory_percent');
  const [forecastData, setForecastData] = useState<ForecastData | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  const { data: metrics } = usePolling(() => api.metrics(), 15_000);

  const containers = metrics?.containers ?? [];

  async function runForecast(id: string) {
    if (!id) return;
    setForecastLoading(true);
    setForecastError(null);
    try {
      const result = await api.forecast(id, horizonHours, metric);
      setForecastData(result);
    } catch (e: unknown) {
      setForecastError(e instanceof Error ? e.message : 'Forecast failed');
      setForecastData(null);
    } finally {
      setForecastLoading(false);
    }
  }

  const chartData = buildChartData(containers, selectedId, forecastData);
  const metricLabel = METRIC_OPTIONS.find(m => m.value === metric)?.label ?? metric;

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Usage Forecast</div>
        <div className="topbar-meta">
          <div className="refresh-badge">📈 On-demand</div>
        </div>
      </div>

      <div className="page-body">
        {/* Controls */}
        <div
          className="card"
          style={{ padding: '20px 24px', marginBottom: 24, display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}
        >
          {/* Container picker */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: '1 1 220px' }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Container
            </label>
            <select
              id="forecast-container-select"
              value={selectedId}
              onChange={e => { setSelectedId(e.target.value); setForecastData(null); }}
              style={{
                background: 'var(--bg-glass)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                padding: '9px 14px',
                fontSize: 13,
                outline: 'none',
              }}
            >
              <option value="">— Select container —</option>
              {containers.map(c => (
                <option key={c.container_id} value={c.container_id}>
                  {c.container_name} ({c.container_id})
                </option>
              ))}
            </select>
          </div>

          {/* Metric picker */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Metric
            </label>
            <select
              id="forecast-metric-select"
              value={metric}
              onChange={e => { setMetric(e.target.value); setForecastData(null); }}
              style={{
                background: 'var(--bg-glass)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                padding: '9px 14px',
                fontSize: 13,
                outline: 'none',
              }}
            >
              {METRIC_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          {/* Horizon picker */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Horizon
            </label>
            <select
              id="forecast-horizon-select"
              value={horizonHours}
              onChange={e => { setHorizonHours(Number(e.target.value)); setForecastData(null); }}
              style={{
                background: 'var(--bg-glass)',
                border: '1px solid var(--border-glass)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                padding: '9px 14px',
                fontSize: 13,
                outline: 'none',
              }}
            >
              {HORIZON_OPTIONS.map(h => <option key={h} value={h}>{h}h ahead</option>)}
            </select>
          </div>

          <button
            id="forecast-run-btn"
            disabled={!selectedId || forecastLoading}
            onClick={() => runForecast(selectedId)}
            style={{
              padding: '10px 24px',
              background: selectedId ? 'var(--grad-primary)' : 'var(--bg-glass)',
              border: 'none',
              borderRadius: 'var(--radius-md)',
              color: selectedId ? '#fff' : 'var(--text-muted)',
              fontWeight: 600,
              fontSize: 13,
              cursor: selectedId ? 'pointer' : 'default',
              transition: 'all 0.2s',
              boxShadow: selectedId ? 'var(--shadow-glow)' : 'none',
            }}
          >
            {forecastLoading ? '⏳ Running…' : '▶ Run Forecast'}
          </button>
        </div>

        {forecastError && <ErrorBanner message={forecastError} />}
        {forecastLoading && <Spinner />}

        {/* Chart */}
        {!forecastLoading && selectedId && (
          <div className="card" style={{ padding: '24px' }}>
            <div className="card-header" style={{ border: 'none', padding: '0 0 16px 0' }}>
              <div className="card-title">
                {metricLabel} Forecast
                {forecastData && (
                  <span className="badge badge-info" style={{ marginLeft: 10 }}>
                    {forecastData.method_used.replace('_', ' ')}
                  </span>
                )}
              </div>
              {forecastData && (
                <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  Predicted in {horizonHours}h:{' '}
                  <strong style={{ color: 'var(--accent-cyan)' }}>
                    {forecastData.predicted_value.toFixed(1)}%
                  </strong>
                  {' '}(±{((forecastData.confidence_high - forecastData.confidence_low) / 2).toFixed(1)})
                </div>
              )}
            </div>

            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={340}>
                <AreaChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="areaActual" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#00d4ff" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="areaPredicted" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#9b6dff" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#9b6dff" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="areaCI" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#9b6dff" stopOpacity={0.12} />
                      <stop offset="95%" stopColor="#9b6dff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(100,150,255,0.07)" />
                  <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} />
                  <YAxis domain={[0, 100]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} unit="%" />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-accent)', borderRadius: 8 }}
                    labelStyle={{ color: 'var(--text-primary)', fontWeight: 600 }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                  <Area
                    type="monotone"
                    dataKey="actual"
                    name="Historical"
                    stroke="#00d4ff"
                    fill="url(#areaActual)"
                    strokeWidth={2}
                    dot={{ fill: '#00d4ff', r: 4 }}
                    connectNulls
                  />
                  {forecastData && (
                    <>
                      <Area
                        type="monotone"
                        dataKey="high"
                        name="CI High"
                        stroke="none"
                        fill="url(#areaCI)"
                        connectNulls
                      />
                      <Area
                        type="monotone"
                        dataKey="predicted"
                        name="Predicted"
                        stroke="#9b6dff"
                        fill="url(#areaPredicted)"
                        strokeWidth={2}
                        strokeDasharray="6 3"
                        dot={{ fill: '#9b6dff', r: 5 }}
                        connectNulls
                      />
                      <Area
                        type="monotone"
                        dataKey="low"
                        name="CI Low"
                        stroke="none"
                        fill="url(#areaCI)"
                        connectNulls
                      />
                      <ReferenceLine
                        x={`+${horizonHours}h`}
                        stroke="rgba(155,109,255,0.4)"
                        strokeDasharray="4 2"
                      />
                    </>
                  )}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-state">
                <div className="empty-icon">📈</div>
                <div className="empty-title">Select a container and click Run Forecast</div>
              </div>
            )}
          </div>
        )}

        {!selectedId && (
          <div className="empty-state">
            <div className="empty-icon">📈</div>
            <div className="empty-title">Choose a container to forecast</div>
            <div className="empty-sub">Select from the dropdown above, then click Run Forecast.</div>
          </div>
        )}
      </div>
    </>
  );
}

