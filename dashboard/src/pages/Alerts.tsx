import { useState, useMemo } from 'react';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { AlertRow } from '../components/AlertBadge';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

type SortKey = 'timestamp' | 'alert_type' | 'container_name' | 'current_value';
type SortDir = 'asc' | 'desc';

function SortButton({ label, sortKey, current, dir, onSort }: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const active = sortKey === current;
  return (
    <th
      style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
      onClick={() => onSort(sortKey)}
    >
      {label}
      {active && <span style={{ marginLeft: 4, opacity: 0.8 }}>{dir === 'desc' ? '▼' : '▲'}</span>}
    </th>
  );
}

export default function Alerts() {
  const { data, loading, error } = usePolling(() => api.alerts(200), 10_000);
  const [sortKey, setSortKey] = useState<SortKey>('timestamp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data.alerts].sort((a, b) => {
      let av: string | number = a[sortKey];
      let bv: string | number = b[sortKey];
      if (typeof av === 'string') av = av.toLowerCase();
      if (typeof bv === 'string') bv = bv.toLowerCase();
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [data, sortKey, sortDir]);

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
              <span className="section-count">{sorted.length} shown</span>
            </div>

            {sorted.length === 0 ? (
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
                        <SortButton label="Type"        sortKey="alert_type"      current={sortKey} dir={sortDir} onSort={handleSort} />
                        <SortButton label="Container"   sortKey="container_name"  current={sortKey} dir={sortDir} onSort={handleSort} />
                        <th>Metric</th>
                        <SortButton label="Value / Thr" sortKey="current_value"   current={sortKey} dir={sortDir} onSort={handleSort} />
                        <SortButton label="Time"        sortKey="timestamp"       current={sortKey} dir={sortDir} onSort={handleSort} />
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map(a => (
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
