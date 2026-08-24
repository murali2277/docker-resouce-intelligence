import React, { useState } from 'react';
import { usePollingInterval } from '../hooks/PollingContext';

const INTERVAL_OPTIONS = [
  { label: '5s',  value: 5_000 },
  { label: '10s', value: 10_000 },
  { label: '15s', value: 15_000 },
  { label: '30s', value: 30_000 },
  { label: '60s', value: 60_000 },
];

export const SettingsModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { intervalMs, setIntervalMs } = usePollingInterval();
  const [selected, setSelected] = useState(intervalMs);

  function handleSave() {
    setIntervalMs(selected);
    onClose();
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 200,
        background: 'rgba(5,11,24,0.88)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{
          width: '100%', maxWidth: 420,
          padding: 28,
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
          ⚙️ Settings
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 24 }}>
          Configure global dashboard behavior
        </div>

        {/* Polling interval */}
        <div style={{ marginBottom: 24 }}>
          <div style={{
            fontSize: 11, fontWeight: 600, color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10,
          }}>
            Polling Interval
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {INTERVAL_OPTIONS.map(opt => (
              <button
                key={opt.value}
                id={`settings-interval-${opt.value}`}
                onClick={() => setSelected(opt.value)}
                style={{
                  padding: '8px 18px',
                  borderRadius: 'var(--radius-md)',
                  border: selected === opt.value
                    ? '2px solid var(--accent-cyan)'
                    : '1px solid var(--border-glass)',
                  background: selected === opt.value
                    ? 'rgba(0,212,255,0.12)'
                    : 'var(--bg-glass)',
                  color: selected === opt.value
                    ? 'var(--accent-cyan)'
                    : 'var(--text-secondary)',
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
            All views will refresh at this interval. Lower values increase API load.
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            id="settings-cancel-btn"
            onClick={onClose}
            style={{
              padding: '9px 20px',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-glass)',
              background: 'var(--bg-glass)',
              color: 'var(--text-secondary)',
              fontWeight: 600,
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          <button
            id="settings-save-btn"
            onClick={handleSave}
            style={{
              padding: '9px 20px',
              borderRadius: 'var(--radius-md)',
              border: 'none',
              background: 'var(--grad-primary)',
              color: '#fff',
              fontWeight: 600,
              fontSize: 13,
              cursor: 'pointer',
              boxShadow: 'var(--shadow-glow)',
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
