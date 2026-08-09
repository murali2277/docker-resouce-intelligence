import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { AlertRow } from '../components/AlertBadge';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

export default function Alerts() {
  const { data, loading, error } = usePolling(() => api.alerts(200), 10_000);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Alert Feed</div>
        <div className="topbar-meta">
          <div className="refresh-badge">🔄 Live · 10s</div>
          {data && <span>{data.total_count} total</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            <div className="section-header">
              <div className="section-title">Recent Alerts</div>
              <span className="section-count">{data.alerts.length} shown</span>
            </div>

            {data.alerts.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">🔔</div>
                <div className="empty-title">No alerts yet</div>
                <div className="empty-sub">Policy violations will appear here in real-time.</div>
              </div>
            ) : (
              <div className="card">
                <div className="card-body" style={{ padding: 0 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Container</th>
                        <th>Metric</th>
                        <th>Value / Threshold</th>
                        <th>Time</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.alerts.map(a => (
                        <AlertRow key={a.alert_id} alert={a} />
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

