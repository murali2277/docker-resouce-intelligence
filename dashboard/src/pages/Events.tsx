import { useState } from 'react';
import { api, type DockerEvent } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { Spinner, ErrorBanner } from '../components/MetricsCard';
import {
  IconOom, IconDie, IconDestroy, IconCreate, IconStart,
  IconStop, IconHealth, IconContainer, IconEmptyBox, IconRestart,
} from '../components/icons';
import type React from 'react';

type IconFC = React.FC<{ size?: number }>;

const EVENT_META: Record<string, { cls: string; Icon: IconFC; rail: string }> = {
  oom:           { cls: 'badge-critical', Icon: IconOom,     rail: 'var(--crit)' },
  die:           { cls: 'badge-warning',  Icon: IconDie,     rail: 'var(--warn)' },
  destroy:       { cls: 'badge-critical', Icon: IconDestroy, rail: 'var(--crit)' },
  create:        { cls: 'badge-info',     Icon: IconCreate,  rail: 'var(--info)' },
  start:         { cls: 'badge-success',  Icon: IconStart,   rail: 'var(--ok)'   },
  stop:          { cls: 'badge-neutral',  Icon: IconStop,    rail: 'var(--line-strong)' },
  health_status: { cls: 'badge-info',     Icon: IconHealth,  rail: 'var(--info)' },
};

function EventRow({ event }: { event: DockerEvent }) {
  const meta = EVENT_META[event.action] ?? { cls: 'badge-neutral', Icon: IconContainer, rail: 'var(--line-strong)' };
  const { Icon } = meta;
  const ts = new Date(event.timestamp).toLocaleString();
  const attrKeys = event.attributes ? Object.keys(event.attributes) : [];

  return (
    <tr
      className="rail-row"
      style={{ '--row-rail': meta.rail } as React.CSSProperties}
    >
      <td>
        <span className={`badge ${meta.cls}`}>
          <Icon size={11} /> {event.action}
        </span>
      </td>
      <td>
        <span style={{ fontWeight: 600 }}>{event.container_name || 'unknown'}</span>
        <br />
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {event.container_id || 'n/a'}
        </span>
      </td>
      <td style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
        {event.event_type || 'container'}
      </td>
      <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {attrKeys.length > 0 ? (
          <code style={{ fontSize: 11, background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: 4 }}>
            {JSON.stringify(event.attributes)}
          </code>
        ) : (
          <span style={{ color: 'var(--text-muted)' }}>—</span>
        )}
      </td>
      <td style={{ fontSize: 12, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
        {ts}
      </td>
    </tr>
  );
}

export default function Events() {
  const { intervalMs } = usePollingInterval();
  const { data, loading, error } = usePolling(() => api.events(undefined, 200), intervalMs);
  const [search, setSearch] = useState('');

  const events = (data?.events ?? []).filter(e => {
    if (!search) return true;
    const term = search.toLowerCase();
    return (
      e.container_name.toLowerCase().includes(term) ||
      e.container_id.toLowerCase().includes(term) ||
      e.action.toLowerCase().includes(term)
    );
  });

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Docker Events</div>
        <div className="topbar-meta">
          <div className="refresh-badge"><IconRestart size={11} /> {(intervalMs / 1000).toFixed(0)}s refresh</div>
          {data && <span>{data.total_count} total events</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            <div className="section-header" style={{ flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="section-title">Lifecycle Event Stream</div>
                <span className="section-count">{events.length} shown</span>
              </div>
              <input
                type="text"
                placeholder="Filter by container or action..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 6,
                  padding: '6px 12px',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  width: 240,
                }}
              />
            </div>

            {events.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon"><IconEmptyBox size={28} /></div>
                <div className="empty-title">No Docker events recorded</div>
                <div className="empty-sub">
                  OOM, die, start, stop, create, and destroy events streamed from the Docker daemon will appear here automatically.
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
                        <th>Type</th>
                        <th>Attributes</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map(ev => (
                        <EventRow key={ev.id} event={ev} />
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
