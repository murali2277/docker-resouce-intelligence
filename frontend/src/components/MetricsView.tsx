import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { ContainerMetricsListResponse } from '../types/api';

interface MetricsViewProps {
  intervalMs: number;
}

export const MetricsView: React.FC<MetricsViewProps> = ({ intervalMs }) => {
  const { data, loading, error, lastUpdated, refetch } = usePolling<ContainerMetricsListResponse>(
    '/api/v1/metrics',
    { intervalMs }
  );

  const getProgressClass = (pct: number) => {
    if (pct >= 85) return 'progress-high';
    if (pct >= 60) return 'progress-medium';
    return 'progress-low';
  };

  return (
    <div>
      <div className="view-header">
        <h2 className="view-title">
          <span>📊</span> Container Metrics
        </h2>
        <div className="view-controls">
          {lastUpdated && (
            <span className="last-updated">
              Updated: {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button onClick={refetch} className="refresh-btn">
            🔄 Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <div className="error-icon">⚠️</div>
          <div>
            <div className="error-title">Failed to load container metrics</div>
            <div className="error-desc">{error}</div>
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="glass-card">
          <div className="state-container">
            <div className="spinner"></div>
            <p style={{ color: 'var(--text-secondary)' }}>Fetching live container metrics...</p>
          </div>
        </div>
      )}

      {data && (
        <div className="glass-card">
          <div className="table-container">
            <table className="custom-table">
              <thead>
                <tr>
                  <th>Container</th>
                  <th>CPU Usage</th>
                  <th>CPU Avg (5m / 15m / 60m)</th>
                  <th>Memory Usage</th>
                  <th>Mem Avg (5m / 15m / 60m)</th>
                  <th>Growth Rate (1m / 5m)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.containers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-state" style={{ textAlign: 'center' }}>
                      No active containers being monitored.
                    </td>
                  </tr>
                ) : (
                  data.containers.map((container) => (
                    <tr key={container.container_id}>
                      <td>
                        <div className="container-name">{container.container_name}</div>
                        <div className="mono-text">{container.container_id.substring(0, 12)}</div>
                      </td>
                      <td style={{ width: '180px' }}>
                        <div style={{ fontWeight: 600 }}>{container.cpu_percent.toFixed(1)}%</div>
                        <div className="progress-bar-bg">
                          <div
                            className={`progress-bar-fill ${getProgressClass(container.cpu_percent)}`}
                            style={{ width: `${Math.min(100, Math.max(0, container.cpu_percent))}%` }}
                          />
                        </div>
                      </td>
                      <td className="mono-text">
                        {container.cpu_percent_5m.toFixed(1)}% / {container.cpu_percent_15m.toFixed(1)}% / {container.cpu_percent_60m.toFixed(1)}%
                      </td>
                      <td style={{ width: '180px' }}>
                        <div style={{ fontWeight: 600 }}>{container.memory_percent.toFixed(1)}%</div>
                        <div className="progress-bar-bg">
                          <div
                            className={`progress-bar-fill ${getProgressClass(container.memory_percent)}`}
                            style={{ width: `${Math.min(100, Math.max(0, container.memory_percent))}%` }}
                          />
                        </div>
                      </td>
                      <td className="mono-text">
                        {container.memory_percent_5m.toFixed(1)}% / {container.memory_percent_15m.toFixed(1)}% / {container.memory_percent_60m.toFixed(1)}%
                      </td>
                      <td className="mono-text">
                        {container.memory_growth_rate_1m.toFixed(2)} / {container.memory_growth_rate_5m.toFixed(2)}
                      </td>
                      <td>
                        {container.is_anomaly ? (
                          <span className="badge badge-danger">
                            ⚠️ Anomaly {container.anomaly_type ? `(${container.anomaly_type})` : ''}
                          </span>
                        ) : (
                          <span className="badge badge-success">✓ Normal</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
