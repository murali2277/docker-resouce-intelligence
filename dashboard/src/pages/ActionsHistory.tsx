import { api, type ActionRecord } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { Spinner, ErrorBanner } from '../components/MetricsCard';
import {
  IconThrottle, IconIsolate, IconRestart, IconHeal,
  IconWebhook, IconScale, IconCheck, IconCritical, IconEmptyBox,
} from '../components/icons';
import type React from 'react';

type IconFC = React.FC<{ size?: number }>;

const ACTION_META: Record<string, { cls: string; Icon: IconFC; rail: string }> = {
  throttle: { cls: 'badge-warning',  Icon: IconThrottle, rail: 'var(--warn)' },
  isolate:  { cls: 'badge-critical', Icon: IconIsolate,  rail: 'var(--crit)' },
  restart:  { cls: 'badge-info',     Icon: IconRestart,  rail: 'var(--info)' },
  heal:     { cls: 'badge-info',     Icon: IconHeal,     rail: 'var(--info)' },
  webhook:  { cls: 'badge-neutral',  Icon: IconWebhook,  rail: 'var(--line-strong)' },
  scale:    { cls: 'badge-neutral',  Icon: IconScale,    rail: 'var(--line-strong)' },
};

function ActionRow({ action }: { action: ActionRecord }) {
  const meta = ACTION_META[action.action_type] ?? { cls: 'badge-neutral', Icon: IconScale, rail: 'var(--line-strong)' };
  const { Icon } = meta;
  const ts = new Date(action.timestamp).toLocaleString();

  return (
    <tr
      className="rail-row"
      style={{ '--row-rail': meta.rail } as React.CSSProperties}
    >
      <td>
        <span className={`badge ${meta.cls}`}>
          <Icon size={11} /> {action.action_type}
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
          <span className="badge badge-success"><IconCheck size={11} /> Success</span>
        ) : (
          <span
            className="badge badge-critical"
            title={action.error_message ?? 'Unknown error'}
          >
            <IconCritical size={11} /> Failed
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
  const { intervalMs } = usePollingInterval();
  const { data, loading, error } = usePolling(() => api.actions(200), intervalMs);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Actions History</div>
        <div className="topbar-meta">
          <div className="refresh-badge">{(intervalMs / 1000).toFixed(0)}s refresh</div>
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
                <div className="empty-icon"><IconEmptyBox size={28} /></div>
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
