import React from 'react';
import type { Alert } from '../api/client';

interface AlertBadgeProps { alertType: string; }

export const AlertBadge: React.FC<AlertBadgeProps> = ({ alertType }) => {
  const map: Record<string, { cls: string; icon: string }> = {
    critical: { cls: 'badge-critical', icon: '🔴' },
    warning:  { cls: 'badge-warning',  icon: '🟡' },
    throttle: { cls: 'badge-warning',  icon: '⚡' },
    isolate:  { cls: 'badge-critical', icon: '🔒' },
    restart:  { cls: 'badge-info',     icon: '🔄' },
    webhook:  { cls: 'badge-neutral',  icon: '📡' },
  };
  const { cls, icon } = map[alertType] ?? { cls: 'badge-neutral', icon: '⚪' };
  return (
    <span className={`badge ${cls}`}>
      {icon} {alertType}
    </span>
  );
};

interface AlertRowProps { alert: Alert; }

export const AlertRow: React.FC<AlertRowProps> = ({ alert }) => {
  const ts = new Date(alert.timestamp).toLocaleString();
  return (
    <tr>
      <td>
        <AlertBadge alertType={alert.alert_type} />
      </td>
      <td>
        <span style={{ fontWeight: 600 }}>{alert.container_name}</span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {alert.container_id}
        </span>
      </td>
      <td>{alert.metric}</td>
      <td>
        <span style={{ color: 'var(--accent-red)', fontWeight: 700 }}>
          {alert.current_value.toFixed(1)}%
        </span>
        {' '}/ {alert.threshold}%
      </td>
      <td style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{ts}</td>
      <td>
        {alert.acknowledged ? (
          <span className="badge badge-success">✓ ACK</span>
        ) : (
          <span className="badge badge-neutral">pending</span>
        )}
      </td>
    </tr>
  );
};
