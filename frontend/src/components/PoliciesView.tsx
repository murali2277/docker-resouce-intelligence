import React from 'react';
import { usePolling } from '../hooks/usePolling';
import { PoliciesResponse } from '../types/api';

interface PoliciesViewProps {
  intervalMs: number;
}

export const PoliciesView: React.FC<PoliciesViewProps> = ({ intervalMs }) => {
  const { data, loading, error, lastUpdated, refetch } = usePolling<PoliciesResponse>(
    '/api/v1/policies',
    { intervalMs }
  );

  return (
    <div>
      <div className="view-header">
        <h2 className="view-title">
          <span>🛡️</span> Active Policies
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
            <div className="error-title">Failed to load active policies</div>
            <div className="error-desc">{error}</div>
          </div>
        </div>
      )}

      {loading && !data && (
        <div className="glass-card">
          <div className="state-container">
            <div className="spinner"></div>
            <p style={{ color: 'var(--text-secondary)' }}>Loading policy engine configuration...</p>
          </div>
        </div>
      )}

      {data && (
        <div>
          {data.policies.length === 0 ? (
            <div className="glass-card">
              <div className="empty-state" style={{ textAlign: 'center' }}>
                No active policies configured.
              </div>
            </div>
          ) : (
            <div className="policies-grid">
              {data.policies.map((policy, idx) => (
                <div className="policy-card" key={policy.name || idx}>
                  <div className="policy-card-header">
                    <div className="policy-name">{policy.name}</div>
                    {policy.enabled ? (
                      <span className="badge badge-success">● Active</span>
                    ) : (
                      <span className="badge badge-secondary">○ Disabled</span>
                    )}
                  </div>

                  <div className="policy-selector">
                    <span style={{ color: 'var(--text-muted)' }}>Target Selector: </span>
                    <span className="mono-text">
                      {policy.selector && Object.keys(policy.selector).length > 0
                        ? JSON.stringify(policy.selector)
                        : 'Global (All Containers)'}
                    </span>
                  </div>

                  <div className="rules-list">
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Evaluation Rules ({policy.rules.length})
                    </div>
                    {policy.rules.map((rule, ruleIdx) => (
                      <div className="rule-item" key={ruleIdx}>
                        <div>
                          <div className="rule-condition">
                            {rule.metric} {rule.operator} {rule.value}%
                          </div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                            For duration: {rule.duration_seconds}s
                          </div>
                        </div>
                        <span className="badge badge-warning">
                          {rule.action}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
