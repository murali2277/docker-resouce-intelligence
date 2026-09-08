import React from 'react';
import type { Alert } from '../api/client';
import {
  IconCritical, IconWarning, IconThrottle, IconIsolate,
  IconRestart, IconWebhook, IconCheck,
} from './icons';

type IconFC = React.FC<{ size?: number }>;

interface AlertBadgeProps { alertType: string; }

export const AlertBadge: React.FC<AlertBadgeProps> = ({ alertType }) => {
  const map: Record<string, { cls: string; Icon: IconFC }> = {
    critical: { cls: 'badge-critical', Icon: IconCritical },
    warning:  { cls: 'badge-warning',  Icon: IconWarning  },
    throttle: { cls: 'badge-warning',  Icon: IconThrottle },
    isolate:  { cls: 'badge-critical', Icon: IconIsolate  },
    restart:  { cls: 'badge-info',     Icon: IconRestart  },
    webhook:  { cls: 'badge-neutral',  Icon: IconWebhook  },
  };
  const entry = map[alertType] ?? { cls: 'badge-neutral', Icon: IconWarning };
  const { cls, Icon } = entry;
  return (
    <span className={`badge ${cls}`}>
      <Icon size={11} /> {alertType}
    </span>
  );
};

interface AlertRowProps { alert: Alert; }

export const AlertRow: React.FC<AlertRowProps> = ({ alert }) => {
  const ts = new Date(alert.timestamp).toLocaleString();
  const severityCls =
    alert.alert_type === 'critical' || alert.alert_type === 'isolate'
      ? 'var(--crit)'
      : alert.alert_type === 'warning' || alert.alert_type === 'throttle'
      ? 'var(--warn)'
      : alert.alert_type === 'restart'
      ? 'var(--info)'
      : 'var(--line-strong)';

  return (
    <tr style={{ '--row-rail': severityCls } as React.CSSProperties} className="rail-row">
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
          <span className="badge badge-success"><IconCheck size={11} /> ACK</span>
        ) : (
          <span className="badge badge-neutral">pending</span>
        )}
      </td>
    </tr>
  );
};
