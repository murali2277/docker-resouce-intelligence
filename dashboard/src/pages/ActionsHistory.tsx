import { api, type ActionRecord } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

const ACTION_META: Record<string, { cls: string; icon: string }> = {
  throttle: { cls: 'badge-warning', icon: '⚡' },
  isolate:  { cls: 'badge-critical', icon: '🔒' },
  restart:  { cls: 'badge-info', icon: '🔄' },
  heal:     { cls: 'badge-info', icon: '💊' },
  webhook:  { cls: 'badge-neutral', icon: '📡' },
  scale:    { cls: 'badge-neutral', icon: '📐' },
};

function ActionRow({ action }: { action: ActionRecord }) {
  const meta = ACTION_META[action.action_type] ?? { cls: 'badge-neutral', icon: '⚙️' };
  const ts = new Date(action.timestamp).toLocaleString();

  return (
    <tr>
      <td>
        <span className={`badge ${meta.cls}`}>
          {meta.icon} {action.action_type}
        </span>
      </td>
      <td>
        <span style={{ fontWeight: 600 }}>{action.container_name}</span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {action.container_id}
        </span>
      </td>
      <td style={{ maxWidth: 320, color: 'var(--text-secondary)', fontSize: 13 }}>
        {action.reason}
      </td>
      <td>
        {action.success ? (
          <span className="badge badge-success">✓ Success</span>
        ) : (
          <span
            className="badge badge-critical"
            title={action.error_message ?? 'Unknown error'}
          >
            ✗ Failed
          </span>
        )}
        {action.error_message && (
          <div style={{ fontSize: 11, color: 'var(--accent-red)', marginTop: 4 }}>
            {action.error_message}
          </div>
        )}
      </td>
      <td style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
        {ts}
      </td>
    </tr>
  );
}

export default function ActionsHistory() {
  const { data, loading, error } = usePolling(() => api.actions(200), 15_000);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Actions History</div>
        <div className="topbar-meta">
          <div className="refresh-badge">🔄 15s refresh</div>
          {data && <span>{data.total_count} total actions</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            <div className="section-header">
              <div className="section-title">Automated Actions Log</div>
              <span className="section-count">{data.actions.length} shown</span>
            </div>

            {data.actions.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">⚙️</div>
                <div className="empty-title">No actions executed yet</div>
                <div className="empty-sub">
                  Throttle, isolate, restart, and webhook actions will appear here
                  once the DRI agent triggers them in response to policy violations.
                </div>
              </div>
            ) : (
              <div className="card">
                <div className="card-body" style={{ padding: 0 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Action</th>
                        <th>Container</th>
                        <th>Reason</th>
                        <th>Result</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.actions.map(a => (
                        <ActionRow key={a.action_id} action={a} />
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
