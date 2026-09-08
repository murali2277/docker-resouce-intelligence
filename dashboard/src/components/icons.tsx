// ──────────────────────────────────────────────────────────────
// DRI Icon Library — stroke-only monoline SVG icons
// viewBox="0 0 16 16", strokeWidth="1.4", fill="none"
// Color is fully inherited (stroke="currentColor") — badges and
// containers drive color via their semantic CSS vars. Never
// hardcode a color here.
// ──────────────────────────────────────────────────────────────

const PROPS = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.4,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

// ── Alert / action types ────────────────────────────────────

/** Critical alert — filled diamond strike */
export function IconCritical({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M8 2L14 8 8 14 2 8Z" />
      <path d="M8 5.5v3M8 10.5v.5" />
    </svg>
  );
}

/** Warning — triangle with exclamation */
export function IconWarning({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M8 2.5 13.5 12.5H2.5L8 2.5Z" />
      <path d="M8 6v3.5M8 10.5v.5" />
    </svg>
  );
}

/** Throttle — downward flow with gate */
export function IconThrottle({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M8 2v12" />
      <path d="M5 5.5h6" />
      <path d="M3 8.5h10" />
      <path d="M5 11.5h6" />
    </svg>
  );
}

/** Isolate — box with lock */
export function IconIsolate({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="3" y="7.5" width="10" height="6.5" rx="1" />
      <path d="M5.5 7.5V5.5a2.5 2.5 0 0 1 5 0v2" />
      <path d="M8 10v2" />
    </svg>
  );
}

/** Restart — circular arrow */
export function IconRestart({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M13 8A5 5 0 1 1 8 3" />
      <path d="M8 1.5V4.5h3" />
    </svg>
  );
}

/** Webhook — signal waves / antenna */
export function IconWebhook({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M8 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4Z" />
      <path d="M5 9a4.5 4.5 0 0 1 6 0" />
      <path d="M3 6.5a7.5 7.5 0 0 1 10 0" />
      <path d="M8 2v2" />
    </svg>
  );
}

/** Heal — cross / medical plus */
export function IconHeal({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="3" y="3" width="10" height="10" rx="1.5" />
      <path d="M8 5.5v5M5.5 8h5" />
    </svg>
  );
}

/** Scale — resize outward arrows */
export function IconScale({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M2 14V10h4M14 2V6h-4M2 14l5-5M14 2 9 7" />
    </svg>
  );
}

// ── Event types ────────────────────────────────────────────

/** OOM — lightning bolt (out-of-memory kill) */
export function IconOom({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M9 2 4 9h5l-2 5 7-8H9l1-4Z" />
    </svg>
  );
}

/** Die — skull / X circle */
export function IconDie({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
    </svg>
  );
}

/** Destroy — trash bin */
export function IconDestroy({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M3 4.5h10M5 4.5V3h6v1.5M12 4.5l-.75 8H4.75L4 4.5" />
      <path d="M6.5 7v4M9.5 7v4" />
    </svg>
  );
}

/** Create — plus in a square */
export function IconCreate({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
      <path d="M8 5.5v5M5.5 8h5" />
    </svg>
  );
}

/** Start — play triangle */
export function IconStart({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M4.5 2.5l8 5.5-8 5.5V2.5Z" />
    </svg>
  );
}

/** Stop — solid square (halt) */
export function IconStop({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="3.5" y="3.5" width="9" height="9" rx="1" />
    </svg>
  );
}

/** Health status — heartbeat / pulse line */
export function IconHealth({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M2 8h2.5L6 5l3 7 2-4 1 2H14" />
    </svg>
  );
}

// ── Status / state ────────────────────────────────────────

/** Check — nominal / stable / success */
export function IconCheck({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M3 8.5l3.5 3.5L13 5" />
    </svg>
  );
}

/** Clock — pending / in-progress */
export function IconClock({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 5v3.2l2 1.3" />
    </svg>
  );
}

/** Idle — crescent moon / sleep */
export function IconIdle({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M11 11.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 11 11.5Z" />
    </svg>
  );
}

/** TrendUp — rising line (memory leak indicator) */
export function IconTrendUp({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M2 11.5L6 7l3 2.5 4.5-6" />
      <path d="M10 4h3.5v3.5" />
    </svg>
  );
}

/** Anomaly — warning diamond (inline, not in a table) */
export function IconAnomaly({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M8 2L14 8 8 14 2 8Z" />
      <path d="M8 5.5V9M8 10.5v.5" />
    </svg>
  );
}

/** Stopped — square with a line through it */
export function IconStopped({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1" />
      <path d="M4 4l8 8" />
    </svg>
  );
}

/** Live — filled circle (inline, replaces pulsing dot concept) */
export function IconLive({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <circle cx="8" cy="8" r="3.5" />
      <circle cx="8" cy="8" r="5.5" strokeOpacity={0.35} />
    </svg>
  );
}

// ── Chrome ────────────────────────────────────────────────

/** Close — X mark */
export function IconClose({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M3 3l10 10M13 3 3 13" />
    </svg>
  );
}

/** Run — play arrow (for buttons) */
export function IconRun({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <path d="M4.5 2.5l8 5.5-8 5.5V2.5Z" />
    </svg>
  );
}

/** EmptyBox — generic empty-state glyph */
export function IconEmptyBox({ size = 14 }: { size?: number }) {
  return (
    <svg {...PROPS} width={size} height={size}>
      <rect x="2.5" y="4" width="11" height="9" rx="1" />
      <path d="M2.5 7h11M5.5 4V2.5h5V4" />
    </svg>
  );
}

/** Container — crate / box glyph (replaces whale emoji) */
export function IconContainer({ size = 14 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}
         strokeLinecap="round" strokeLinejoin="round" width={size} height={size}>
      <rect x="4" y="5" width="16" height="14" rx="1" />
      <path d="M4 12h16M9 5v14M15 5v14" />
    </svg>
  );
}
