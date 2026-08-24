import { api, type Policy, type PolicyRule } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { usePollingInterval } from '../hooks/PollingContext';
import { Spinner, ErrorBanner } from '../components/MetricsCard';

const ACTION_BADGE: Record<string, { cls: string; icon: string }> = {
  warning:  { cls: 'badge-warning',  icon: '🟡' },
  throttle: { cls: 'badge-critical', icon: '⚡' },
  isolate:  { cls: 'badge-critical', icon: '🔒' },
  restart:  { cls: 'badge-info',     icon: '🔄' },
  heal:     { cls: 'badge-info',     icon: '💊' },
  webhook:  { cls: 'badge-neutral',  icon: '📡' },
};

function RuleRow({ rule, idx }: { rule: PolicyRule; idx: number }) {
  const meta = ACTION_BADGE[rule.action] ?? { cls: 'badge-neutral', icon: '⚙️' };

  return (
    <tr>
      <td style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--accent-cyan)' }}>
        {idx + 1}
      </td>
      <td>
        <code style={{
          background: 'rgba(0,212,255,0.08)',
          padding: '3px 8px',
          borderRadius: 'var(--radius-sm)',
          fontSize: 12,
          color: 'var(--text-primary)',
        }}>
          {rule.metric}
        </code>
      </td>
      <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>
        {rule.operator}
      </td>
      <td style={{ fontWeight: 700, color: 'var(--accent-amber)' }}>
        {rule.value}%
      </td>
      <td style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
        {rule.duration_seconds}s
      </td>
      <td>
        <span className={`badge ${meta.cls}`}>
          {meta.icon} {rule.action}
        </span>
      </td>
    </tr>
  );
}

function PolicyCard({ policy }: { policy: Policy }) {
  const selectorKeys = Object.keys(policy.selector);
  const isGlobal = selectorKeys.length === 0;

  return (
    <div className="card" style={{ marginBottom: 24, overflow: 'hidden' }}>
      {/* Policy header */}
      <div
        className="card-header"
        style={{
          background: isGlobal
            ? 'linear-gradient(135deg, rgba(77,124,254,0.12) 0%, rgba(0,212,255,0.08) 100%)'
            : 'linear-gradient(135deg, rgba(155,109,255,0.12) 0%, rgba(0,229,160,0.08) 100%)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 20 }}>{isGlobal ? '🌐' : '📦'}</span>
          <div>
            <div className="card-title" style={{ marginBottom: 2 }}>
              {policy.name}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {isGlobal ? 'Global default policy' : 'Per-container policy'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Selector pills */}
          {selectorKeys.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {selectorKeys.map(k => (
                <span
                  key={k}
                  className="badge badge-info"
                  style={{ fontSize: 10 }}
                >
                  {k}: {policy.selector[k]}
                </span>
              ))}
            </div>
          )}

          {/* Enabled / disabled */}
          <span className={`badge ${policy.enabled ? 'badge-success' : 'badge-neutral'}`}>
            {policy.enabled ? '● Active' : '○ Disabled'}
          </span>
        </div>
      </div>

      {/* Rules table */}
      <div className="card-body" style={{ padding: 0 }}>
        {policy.rules.length === 0 ? (
          <div style={{ padding: '20px 24px', color: 'var(--text-muted)', fontSize: 13 }}>
            No rules defined for this policy.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>#</th>
                <th>Metric</th>
                <th>Op</th>
                <th>Threshold</th>
                <th>Duration</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {policy.rules.map((r, i) => (
                <RuleRow key={`${r.metric}-${r.operator}-${r.value}-${i}`} rule={r} idx={i} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default function Policies() {
  const { intervalMs } = usePollingInterval();
  const { data, loading, error } = usePolling(() => api.policies(), intervalMs);

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Policies</div>
        <div className="topbar-meta">
          <div className="refresh-badge">🔄 {(intervalMs / 1000).toFixed(0)}s refresh</div>
          {data && <span>{data.total_count} polic{data.total_count === 1 ? 'y' : 'ies'}</span>}
        </div>
      </div>

      <div className="page-body">
        {error && <ErrorBanner message={error} />}
        {loading && !data && <Spinner />}

        {data && (
          <>
            <div
              style={{
                marginBottom: 24,
                padding: '14px 20px',
                background: 'rgba(155,109,255,0.07)',
                border: '1px solid rgba(155,109,255,0.15)',
                borderRadius: 'var(--radius-md)',
                fontSize: 13,
                color: 'var(--text-secondary)',
                lineHeight: 1.6,
              }}
            >
              📋 Policies define the threshold rules that trigger alerts and automated actions.
              The <strong>global policy</strong> applies to all containers; per-container policies
              add overrides via <strong>selectors</strong> (image name, container ID).
              Rules specify a <strong>metric + operator + threshold</strong>, a <strong>duration</strong> before
              triggering, and the resulting <strong>action</strong>.
            </div>

            <div className="section-header">
              <div className="section-title">Active Policies</div>
              <span className="section-count">
                {data.policies.length} polic{data.policies.length === 1 ? 'y' : 'ies'} · {data.policies.reduce((n, p) => n + p.rules.length, 0)} rules
              </span>
            </div>

            {data.policies.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">📋</div>
                <div className="empty-title">No policies configured</div>
                <div className="empty-sub">
                  Add policies to config.yaml to define threshold rules for your containers.
                </div>
              </div>
            ) : (
              data.policies.map((p, i) => (
                <PolicyCard key={`${p.name}-${i}`} policy={p} />
              ))
            )}
          </>
        )}
      </div>
    </>
  );
}
