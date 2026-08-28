import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { AlertsResponse } from '../types/api';

interface AlertsViewProps {
  intervalMs: number;
}

export const AlertsView: React.FC<AlertsViewProps> = ({ intervalMs }) => {
  const { data, loading, error, lastUpdated, refetch } = usePolling<AlertsResponse>(
    '/api/v1/alerts',
    { intervalMs }
  );

  return (
    <div>
      <div className="view-header">
        <h2 className="view-title">
          <span>🚨</span> Triggered Alerts
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
            <div className="error-title">Failed to load alerts</div>
            <div className="error-desc">{error}</div>
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="glass-card">
          <div className="state-container">
            <div className="spinner"></div>
            <p style={{ color: 'var(--text-secondary)' }}>Loading alerts feed...</p>
          </div>
        </div>
      )}

      {data && (
        <div className="glass-card">
          <div className="table-container">
            <table className="custom-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Container</th>
                  <th>Alert Type</th>
                  <th>Metric</th>
                  <th>Current / Threshold</th>
                  <th>Message</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {data.alerts.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-state" style={{ textAlign: 'center' }}>
                      No alerts triggered yet.
                    </td>
                  </tr>
                ) : (
                  data.alerts.map((alert) => (
                    <tr key={alert.alert_id}>
                      <td style={{ whiteSpace: 'nowrap', fontSize: '0.8125rem' }}>
                        {new Date(alert.timestamp).toLocaleString()}
                      </td>
                      <td>
                        <div className="container-name">{alert.container_name}</div>
                        <div className="mono-text">{alert.container_id.substring(0, 12)}</div>
                      </td>
                      <td>
                        <span className="badge badge-warning">
                          {alert.alert_type}
                        </span>
                      </td>
                      <td className="mono-text">{alert.metric}</td>
                      <td className="mono-text">
                        <span style={{ color: 'var(--status-danger)', fontWeight: 600 }}>
                          {alert.current_value.toFixed(1)}
                        </span>
                        {' / '}
                        <span>{alert.threshold.toFixed(1)}</span>
                      </td>
                      <td style={{ maxWidth: '300px' }}>{alert.message}</td>
                      <td>
                        {alert.acknowledged ? (
                          <span className="badge badge-secondary">Acknowledged</span>
                        ) : (
                          <span className="badge badge-danger">Active</span>
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
