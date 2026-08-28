import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { SettingsModal } from './SettingsModal';

const NAV = [
  { to: '/',               icon: '📊', label: 'Overview' },
  { to: '/alerts',         icon: '🔔', label: 'Alert Feed' },
  { to: '/recommendations',icon: '💡', label: 'Recommendations' },
  { to: '/forecast',       icon: '📈', label: 'Forecast' },
  { to: '/actions',        icon: '⚙️', label: 'Actions History' },
  { to: '/events',         icon: '📡', label: 'Docker Events' },
  { to: '/policies',       icon: '📋', label: 'Policies' },
];

export const Sidebar: React.FC = () => {
  const loc = useLocation();
  const { intervalMs } = usePollingInterval();
  const { data } = usePolling(() => api.health(), intervalMs);
  const [showSettings, setShowSettings] = useState(false);

  return (
    <>
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}

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

        {/* Settings button */}
        <div style={{ padding: '8px 12px' }}>
          <button
            id="open-settings-btn"
            onClick={() => setShowSettings(true)}
            className="nav-link"
            style={{
              width: '100%',
              background: 'none',
              border: 'none',
              textAlign: 'left',
              fontSize: 13.5,
            }}
          >
            <span className="nav-icon">⚙️</span>
            Settings
          </button>
        </div>

        {data && (
          <div className="sidebar-status">
            <div className="status-dot-row">
              <div className="status-dot" />
              <span>DRI {data.version} · {Math.round(data.uptime_seconds / 3600)}h up</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, marginLeft: 16 }}>
              Polling: {(intervalMs / 1000).toFixed(0)}s
            </div>
          </div>
        )}
      </aside>
    </>
  );
};
