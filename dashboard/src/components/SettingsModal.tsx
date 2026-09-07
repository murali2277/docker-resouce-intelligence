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
        background: 'rgba(10,13,17,0.88)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: '100%', maxWidth: 420, padding: 28 }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--paper)', marginBottom: 4 }}>
          Settings
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 24 }}>
          Configure global dashboard behaviour
        </div>

        {/* Polling interval */}
        <div style={{ marginBottom: 24 }}>
          <div style={{
            fontSize: 11, fontWeight: 600, color: 'var(--muted)',
            letterSpacing: '0.04em', marginBottom: 10,
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
                  padding: '7px 16px',
                  borderRadius: 'var(--r-sm)',
                  border: selected === opt.value
                    ? '1px solid var(--signal)'
                    : '1px solid var(--line)',
                  background: selected === opt.value
                    ? 'var(--signal-dim)'
                    : 'var(--panel-soft)',
                  color: selected === opt.value
                    ? 'var(--signal)'
                    : 'var(--paper-soft)',
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: 'pointer',
                  fontFamily: 'var(--font-mono)',
                  transition: 'all 0.12s ease',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
            All views refresh at this interval. Lower values increase API load.
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            id="settings-cancel-btn"
            onClick={onClose}
            style={{
              padding: '8px 18px',
              borderRadius: 'var(--r-sm)',
              border: '1px solid var(--line)',
              background: 'var(--panel-soft)',
              color: 'var(--paper-soft)',
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
              padding: '8px 18px',
              borderRadius: 'var(--r-sm)',
              border: 'none',
              background: 'var(--signal)',
              color: '#0A0D11',
              fontWeight: 700,
              fontSize: 13,
              cursor: 'pointer',
              boxShadow: 'var(--shadow-ring)',
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};
