import React, { useState } from 'react';
import { MetricsView } from './components/MetricsView';
import { AlertsView } from './components/AlertsView';
import { ActionHistoryView } from './components/ActionHistoryView';
import { PoliciesView } from './components/PoliciesView';

type TabType = 'metrics' | 'alerts' | 'actions' | 'policies';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('metrics');
  const [intervalMs, setIntervalMs] = useState<number>(5000);

  return (
    <div className="app-container">
      {/* Header Navigation */}
      <header className="header-bar">
        <div className="brand">
          <div className="brand-logo">🐳</div>
          <div>
            <div className="brand-title">Docker Resource Intelligence</div>
            <div className="brand-subtitle">Real-time Monitoring & Self-Healing Dashboard</div>
          </div>
        </div>

        {/* View Tabs */}
        <nav className="nav-tabs">
          <button
            className={`nav-tab ${activeTab === 'metrics' ? 'active' : ''}`}
            onClick={() => setActiveTab('metrics')}
          >
            <span>📊</span> Metrics
          </button>
          <button
            className={`nav-tab ${activeTab === 'alerts' ? 'active' : ''}`}
            onClick={() => setActiveTab('alerts')}
          >
            <span>🚨</span> Alerts
          </button>
          <button
            className={`nav-tab ${activeTab === 'actions' ? 'active' : ''}`}
            onClick={() => setActiveTab('actions')}
          >
            <span>⚡</span> Action History
          </button>
          <button
            className={`nav-tab ${activeTab === 'policies' ? 'active' : ''}`}
            onClick={() => setActiveTab('policies')}
          >
            <span>🛡️</span> Policies
          </button>
        </nav>

        {/* Status & Polling Config */}
        <div className="header-status">
          <select
            value={intervalMs}
            onChange={(e) => setIntervalMs(Number(e.target.value))}
            style={{
              background: 'rgba(0, 0, 0, 0.4)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-color)',
              padding: '0.35rem 0.6rem',
              borderRadius: '0.5rem',
              fontSize: '0.75rem',
              fontFamily: 'var(--font-sans)',
              cursor: 'pointer',
            }}
          >
            <option value={5000}>Poll: 5s</option>
            <option value={10000}>Poll: 10s</option>
            <option value={15000}>Poll: 15s</option>
          </select>

          <div className="polling-badge">
            <div className="pulse-dot"></div>
            Live Polling
          </div>
        </div>
      </header>

      {/* Main View Area */}
      <main className="main-content">
        {activeTab === 'metrics' && <MetricsView intervalMs={intervalMs} />}
        {activeTab === 'alerts' && <AlertsView intervalMs={intervalMs} />}
        {activeTab === 'actions' && <ActionHistoryView intervalMs={intervalMs} />}
        {activeTab === 'policies' && <PoliciesView intervalMs={intervalMs} />}
      </main>
    </div>
  );
};

export default App;
