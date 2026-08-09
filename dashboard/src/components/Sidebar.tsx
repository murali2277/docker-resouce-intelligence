import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';

const NAV = [
  { to: '/',               icon: '📊', label: 'Overview' },
  { to: '/alerts',         icon: '🔔', label: 'Alert Feed' },
  { to: '/recommendations',icon: '💡', label: 'Recommendations' },
  { to: '/forecast',       icon: '📈', label: 'Forecast' },
];

export const Sidebar: React.FC = () => {
  const loc = useLocation();
  const { data } = usePolling(() => api.health(), 15_000);

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">🐳</div>
        <div>
          <div className="sidebar-logo-text">DRI</div>
          <div className="sidebar-logo-sub">Resource Intelligence</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-label">Navigation</div>
        {NAV.map(n => (
          <Link
            key={n.to}
            to={n.to}
            className={`nav-link ${loc.pathname === n.to ? 'active' : ''}`}
          >
            <span className="nav-icon">{n.icon}</span>
            {n.label}
          </Link>
        ))}
      </nav>

      {data && (
        <div className="sidebar-status">
          <div className="status-dot-row">
            <div className="status-dot" />
            <span>DRI {data.version} · {Math.round(data.uptime_seconds / 3600)}h up</span>
          </div>
        </div>
      )}
    </aside>
  );
};
