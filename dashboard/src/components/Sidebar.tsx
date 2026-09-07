import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { SettingsModal } from './SettingsModal';

// ── Minimal monoline icon set (stroke = currentColor) ───────────────
const IconGrid = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
    <rect x="2" y="2" width="5" height="5" rx="0.5" />
    <rect x="9" y="2" width="5" height="5" rx="0.5" />
    <rect x="2" y="9" width="5" height="5" rx="0.5" />
    <rect x="9" y="9" width="5" height="5" rx="0.5" />
  </svg>
);

const IconBell = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 6.5a4 4 0 0 1 8 0c0 3 1 4 1 4H3s1-1 1-4Z" />
    <path d="M6.5 12.5a1.6 1.6 0 0 0 3 0" />
  </svg>
);

const IconGauge = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2.5 11.5a5.5 5.5 0 0 1 11 0" />
    <path d="M8 11.5 10.5 7" />
    <path d="M2.5 11.5h11" />
  </svg>
);

const IconTrend = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2.5 11 6 6.5 9 9l4.5-6" />
    <path d="M10.5 3h3v3" />
  </svg>
);

const IconHistory = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M8 4v4l2.5 1.5" />
    <path d="M3 8a5 5 0 1 0 1.5-3.5" />
    <path d="M2.5 2.5v2.3h2.3" />
  </svg>
);

const IconEvents = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="8" cy="8" r="5.5" />
    <path d="M8 5v3.5l2 1" />
  </svg>
);

const IconList = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
    <path d="M5.5 4h7M5.5 8h7M5.5 12h7" />
    <path d="M2.7 4h.01M2.7 8h.01M2.7 12h.01" />
  </svg>
);

const IconCrate = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="5" width="16" height="14" rx="1" />
    <path d="M4 12h16M9 5v14M15 5v14" />
  </svg>
);

const IconSettings = () => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="8" cy="8" r="2" />
    <path d="M8 2v1.5M8 12.5V14M14 8h-1.5M3.5 8H2M12 4l-1 1M5 11l-1 1M12 12l-1-1M5 5 4 4" />
  </svg>
);

const NAV = [
  { to: '/',                icon: IconGrid,    label: 'Overview' },
  { to: '/alerts',          icon: IconBell,    label: 'Alert Feed' },
  { to: '/recommendations', icon: IconGauge,   label: 'Recommendations' },
  { to: '/forecast',        icon: IconTrend,   label: 'Forecast' },
  { to: '/actions',         icon: IconHistory, label: 'Actions History' },
  { to: '/events',          icon: IconEvents,  label: 'Docker Events' },
  { to: '/policies',        icon: IconList,    label: 'Policies' },
];

function fmtUptime(s: number): string {
  const h = s / 3600;
  if (h >= 24) return `${(h / 24).toFixed(1)}d`;
  if (h >= 1)  return `${h.toFixed(1)}h`;
  return `${Math.round(s / 60)}m`;
}

export const Sidebar: React.FC = () => {
  const loc = useLocation();
  const { intervalMs } = usePollingInterval();
  const { data } = usePolling(() => api.health(), intervalMs);
  const [showSettings, setShowSettings] = useState(false);

  return (
    <>
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}

      <aside className="sidebar">
        {/* Logo */}
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">
            <IconCrate />
          </div>
          <div>
            <div className="sidebar-logo-text">DRI</div>
            <div className="sidebar-logo-sub">Resource Intelligence</div>
          </div>
        </div>

        {/* Nav links */}
        <nav className="sidebar-nav">
          <div className="nav-label">Navigation</div>
          {NAV.map(n => {
            const Icon = n.icon;
            return (
              <Link
                key={n.to}
                to={n.to}
                className={`nav-link ${loc.pathname === n.to ? 'active' : ''}`}
              >
                <span className="nav-icon"><Icon /></span>
                {n.label}
              </Link>
            );
          })}
        </nav>

        {/* Settings button */}
        <div style={{ padding: '0 10px 8px' }}>
          <button
            id="open-settings-btn"
            onClick={() => setShowSettings(true)}
            className="nav-link"
            style={{
              width: '100%',
              background: 'none',
              border: 'none',
              borderLeft: '2px solid transparent',
              textAlign: 'left',
              fontSize: 13,
            }}
          >
            <span className="nav-icon"><IconSettings /></span>
            Settings
          </button>
        </div>

        {/* Live status readout */}
        {data && (
          <div className="sidebar-status">
            <div className="status-row">
              <div className="status-dot" />
              <span>Live</span>
            </div>
            <div className="status-readout">
              <div className="status-readout-row">
                <span>version</span>
                <span>{data.version}</span>
              </div>
              <div className="status-readout-row">
                <span>uptime</span>
                <span>{fmtUptime(data.uptime_seconds)}</span>
              </div>
              <div className="status-readout-row">
                <span>poll</span>
                <span>{(intervalMs / 1000).toFixed(0)}s</span>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
};
