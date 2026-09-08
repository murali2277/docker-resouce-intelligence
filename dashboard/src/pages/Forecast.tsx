import { useState } from 'react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts';
import { api, type ForecastData, type ContainerMetrics } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { Spinner, ErrorBanner } from '../components/MetricsCard';
import { IconRun, IconClock, IconEmptyBox } from '../components/icons';

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

  const history = [
    { name: 'now',    actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent    : container.memory_percent    },
    { name: '5m avg', actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_5m : container.memory_percent_5m },
    { name: '15m avg',actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_15m: container.memory_percent_15m },
    { name: '60m avg',actual: forecast?.metric === 'cpu_percent' ? container.cpu_percent_60m: container.memory_percent_60m },
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

// Shared select field style for the segmented control bar
const segFieldStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  color: 'var(--text-primary)',
  padding: '10px 14px',
  fontSize: 13,
  outline: 'none',
  cursor: 'pointer',
  width: '100%',
};

export default function Forecast() {
  const [selectedId, setSelectedId] = useState<string>('');
  const [horizonHours, setHorizonHours] = useState(24);
  const [metric, setMetric] = useState('memory_percent');
  const [forecastData, setForecastData] = useState<ForecastData | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);

  const { intervalMs } = usePollingInterval();
  const { data: metrics } = usePolling(() => api.metrics(), intervalMs);

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
          <div className="refresh-badge">On-demand</div>
        </div>
      </div>

      <div className="page-body">
        {/* Segmented control bar — single unified panel, hairlines between fields */}
        <div className="segment-bar" style={{ marginBottom: 24 }}>
          {/* Container picker */}
          <div className="segment-field" style={{ flex: '1 1 220px' }}>
            <label className="segment-label">Container</label>
            <select
              id="forecast-container-select"
              value={selectedId}
              onChange={e => { setSelectedId(e.target.value); setForecastData(null); }}
              style={segFieldStyle}
            >
              <option value="">— Select container —</option>
              {containers.map(c => (
                <option key={c.container_id} value={c.container_id}>
                  {c.container_name} ({c.container_id})
                </option>
              ))}
            </select>
          </div>

          <div className="segment-divider" />

          {/* Metric picker */}
          <div className="segment-field">
            <label className="segment-label">Metric</label>
            <select
              id="forecast-metric-select"
              value={metric}
              onChange={e => { setMetric(e.target.value); setForecastData(null); }}
              style={segFieldStyle}
            >
              {METRIC_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <div className="segment-divider" />

          {/* Horizon picker */}
          <div className="segment-field">
            <label className="segment-label">Horizon</label>
            <select
              id="forecast-horizon-select"
              value={horizonHours}
              onChange={e => { setHorizonHours(Number(e.target.value)); setForecastData(null); }}
              style={segFieldStyle}
            >
              {HORIZON_OPTIONS.map(h => <option key={h} value={h}>{h}h ahead</option>)}
            </select>
          </div>

          <div className="segment-divider" />

          {/* Run button */}
          <div className="segment-field" style={{ flexShrink: 0 }}>
            <label className="segment-label">&nbsp;</label>
            <button
              id="forecast-run-btn"
              disabled={!selectedId || forecastLoading}
              onClick={() => runForecast(selectedId)}
              style={{
                padding: '10px 20px',
                background: selectedId && !forecastLoading ? 'var(--signal)' : 'transparent',
                border: 'none',
                color: selectedId && !forecastLoading ? 'var(--paper)' : 'var(--text-muted)',
                fontWeight: 600,
                fontSize: 13,
                cursor: selectedId ? 'pointer' : 'default',
                transition: 'background var(--fast) var(--ease), color var(--fast) var(--ease)',
                display: 'flex',
                alignItems: 'center',
                gap: 7,
                whiteSpace: 'nowrap',
                width: '100%',
              }}
            >
              {forecastLoading
                ? <><IconClock size={13} /> Running…</>
                : <><IconRun size={13} /> Run Forecast</>
              }
            </button>
          </div>
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
                  <strong style={{ color: 'var(--info)', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>
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
                    {/* Use --info (slate blue) for historical, --signal (orange) for predicted */}
                    <linearGradient id="areaActual" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="var(--info)" stopOpacity={0.28} />
                      <stop offset="95%" stopColor="var(--info)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="areaPredicted" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="var(--signal)" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="var(--signal)" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="areaCI" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="var(--signal)" stopOpacity={0.1} />
                      <stop offset="95%" stopColor="var(--signal)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(33,41,50,0.8)" />
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
                    stroke="var(--info)"
                    fill="url(#areaActual)"
                    strokeWidth={2}
                    dot={{ fill: 'var(--info)', r: 4 }}
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
                        stroke="var(--signal)"
                        fill="url(#areaPredicted)"
                        strokeWidth={2}
                        strokeDasharray="6 3"
                        dot={{ fill: 'var(--signal)', r: 5 }}
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
                        stroke="var(--signal)"
                        strokeOpacity={0.35}
                        strokeDasharray="4 2"
                      />
                    </>
                  )}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-state">
                <div className="empty-icon"><IconEmptyBox size={28} /></div>
                <div className="empty-title">Select a container and click Run Forecast</div>
              </div>
            )}
          </div>
        )}

        {!selectedId && (
          <div className="empty-state">
            <div className="empty-icon"><IconEmptyBox size={28} /></div>
            <div className="empty-title">Choose a container to forecast</div>
            <div className="empty-sub">Select from the dropdown above, then click Run Forecast.</div>
          </div>
        )}
      </div>
    </>
  );
}
