import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { ActionHistoryListResponse } from '../types/api';

interface ActionHistoryViewProps {
  intervalMs: number;
}

export const ActionHistoryView: React.FC<ActionHistoryViewProps> = ({ intervalMs }) => {
  const { data, loading, error, lastUpdated, refetch } = usePolling<ActionHistoryListResponse>(
    '/api/v1/actions/history',
    { intervalMs }
  );

  const getActionBadgeClass = (actionType: string) => {
    switch (actionType.toLowerCase()) {
      case 'throttle':
        return 'badge-warning';
      case 'isolate':
        return 'badge-info';
      case 'heal':
      case 'restart':
        return 'badge-danger';
      default:
        return 'badge-secondary';
    }
  };

  return (
    <div>
      <div className="view-header">
        <h2 className="view-title">
          <span>⚡</span> Action Execution History
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
            <div className="error-title">Failed to load action history</div>
            <div className="error-desc">{error}</div>
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="glass-card">
          <div className="state-container">
            <div className="spinner"></div>
            <p style={{ color: 'var(--text-secondary)' }}>Loading action log...</p>
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
                  <th>Action ID</th>
                  <th>Container</th>
                  <th>Action Type</th>
                  <th>Reason</th>
                  <th>Outcome</th>
                  <th>Error / Details</th>
                </tr>
              </thead>
              <tbody>
                {data.actions.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-state" style={{ textAlign: 'center' }}>
                      No automated actions executed yet.
                    </td>
                  </tr>
                ) : (
                  data.actions.map((action) => (
                    <tr key={action.action_id}>
                      <td style={{ whiteSpace: 'nowrap', fontSize: '0.8125rem' }}>
                        {new Date(action.timestamp).toLocaleString()}
                      </td>
                      <td className="mono-text">{action.action_id.substring(0, 8)}</td>
                      <td>
                        <div className="container-name">{action.container_name}</div>
                        <div className="mono-text">{action.container_id.substring(0, 12)}</div>
                      </td>
                      <td>
                        <span className={`badge ${getActionBadgeClass(action.action_type)}`}>
                          {action.action_type}
                        </span>
                      </td>
                      <td style={{ maxWidth: '280px' }}>{action.reason}</td>
                      <td>
                        {action.success ? (
                          <span className="badge badge-success">✓ Success</span>
                        ) : (
                          <span className="badge badge-danger">✗ Failed</span>
                        )}
                      </td>
                      <td style={{ maxWidth: '250px', fontSize: '0.8125rem', color: action.error_message ? 'var(--status-danger)' : 'var(--text-muted)' }}>
                        {action.error_message || 'None'}
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
